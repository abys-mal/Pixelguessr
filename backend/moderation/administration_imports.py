import hashlib
import logging

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from library.image_processing import convert_image
from library.local_import import UNVERIFIED, register_image
from library.models import Category, ImageSubmission, ImportBatch, ImportItem
from library.serializers import SubmissionSerializer

from .administration import audit, require_administrator


def upload_item(actor, batch_id, request_id, upload, metadata=None):
    created_files = []
    try:
        return _upload_item(actor, batch_id, request_id, upload, created_files, metadata or {})
    except Exception:
        for storage, name in created_files:
            try:
                storage.delete(name)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to clean a new browser import file: %s", name
                )
        raise


def _upload_item(actor, batch_id, request_id, upload, created_files, metadata):
    actor = require_administrator(actor)
    # Decode outside the DB transaction; durable batch locking precedes all mutable reads.
    converted = error = None
    try:
        upload.seek(0)
        source_sha = hashlib.file_digest(upload, "sha256").hexdigest()
        upload.seek(0)
        converted = convert_image(upload, resize=True)
    except Exception:
        error = "Invalid image: use a still JPG, PNG or WebP up to 8 MiB and at least 64 pixels per side."
    with transaction.atomic():
        ImportBatch.objects.filter(pk=batch_id).update(name=F("name"))
        batch = get_object_or_404(ImportBatch, pk=batch_id)
        actor = require_administrator(actor)
        previous = ImportItem.objects.filter(request_id=request_id).first()
        if previous:
            if previous.batch_id != batch.pk:
                raise ValidationError("Upload request ID belongs to another batch.")
            return previous
        name = upload.name[:255]
        if error:
            item = ImportItem.objects.create(
                batch=batch, request_id=request_id, filename=name, status="failed", error=error
            )
        else:

            class Prepared(SubmissionSerializer):
                def validate_image_file(self, value):
                    return value

            category = Category.objects.order_by("pk").first()
            if not category:
                raise ValidationError("Create an image category before uploading.")
            serializer = Prepared(
                data={
                    "canonical_answer": "Unlabeled image",
                    "accepted_synonyms": [],
                    "category": category.pk,
                    "source": metadata.get("source", "manual"),
                    "source_url": metadata.get("source_url", ""),
                    "license": metadata.get("license") or UNVERIFIED,
                    "attribution": metadata.get("attribution") or UNVERIFIED,
                    "image_file": converted.file,
                }
            )
            serializer.is_valid(raise_exception=True)
            meta = {
                "original_filename": name,
                "source_sha256": source_sha,
                "description": "",
                "difficulty": "medium",
                "photographer": metadata.get("photographer", ""),
                "import_kind": "browser",
                "review_notes": "Browser import; label review required.",
                "label_verified": False,
                "metadata_verified": False,
            }
            try:
                image = ImageSubmission.objects.filter(local_import_digest=converted.digest).first()
                result = "duplicate"
                if image is None:
                    result, image, _ = register_image(
                        {"original_filename": name},
                        serializer.validated_data,
                        meta,
                        converted,
                        actor,
                        cleanup_error=logging.getLogger(__name__).error,
                    )
                    if result == "imported_pending":
                        created_files.append((image.image_file.storage, image.image_file.name))
            except Exception as exc:
                raise ValidationError(
                    "Image storage/registration failed; retry the upload."
                ) from exc
            item = ImportItem.objects.create(
                batch=batch,
                request_id=request_id,
                filename=name,
                image=image,
                status="uploaded" if result == "imported_pending" else "duplicate",
            )
        batch.save(update_fields=["updated_at"])
        audit(
            actor,
            "image_import",
            ("import_batch", batch.pk),
            {},
            {
                "item_id": str(item.pk),
                "status": item.status,
                "image_id": str(item.image_id) if item.image_id else None,
            },
        )
        return item
