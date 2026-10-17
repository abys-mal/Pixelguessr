"""Local photograph imports use the normal library, private storage and review gate."""

import csv
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from PIL import Image

from .image_processing import convert_image
from .models import Category, ImageSubmission
from .serializers import SubmissionSerializer

FIELDS = [
    "original_filename",
    "canonical_answer",
    "accepted_synonyms",
    "category",
    "description",
    "difficulty",
    "photographer",
    "pexels_source_url",
    "license",
    "sha256",
    "import_status",
    "review_notes",
    "label_verified",
    "metadata_verified",
    "image_id",
    "content_sha256",
    "storage_name",
    "stored_sha256",
    "width",
    "height",
    "error",
]
UNVERIFIED = "UNVERIFIED"
PROTOTYPE_ATTRIBUTION = "Pexels"
PROTOTYPE_LICENSE = "Pexels License"


def read_manifest(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or set(reader.fieldnames) != set(FIELDS):
            raise ValueError("Manifest columns do not match the documented import format.")
        rows = list(reader)
    names = [row["original_filename"] for row in rows]
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("The manifest contains malformed CSV rows.")
    if len(names) != len(set(names)):
        raise ValueError("The manifest has duplicate original filenames.")
    return rows


def write_manifest(path, rows):
    """Replace atomically; interrupted imports can recover from durable content digests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".import-", suffix=".csv", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if attempt == 5:
                    raise PermissionError(
                        f"Manifest is locked: {path}. Close it in Excel or another editor, then rerun the command."
                    ) from exc
                time.sleep(0.05 * 2**attempt)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verified(value):
    if str(value).strip().lower() not in {"", "yes", "no"}:
        raise ValueError("Verification fields must be yes or no.")
    return str(value).strip().lower() == "yes"


def known(value):
    return (
        bool(value.strip())
        and "unverified" not in value.casefold()
        and "unknown" not in value.casefold()
    )


def validate_approval(image):
    meta = image.local_import_metadata
    url = urlsplit(image.source_url)
    if settings.PEXELS_PROTOTYPE_METADATA:
        if (
            meta.get("label_verified") is not True
            or not known(image.canonical_answer)
            or image.attribution != PROTOTYPE_ATTRIBUTION
            or image.license != PROTOTYPE_LICENSE
            or (
                image.source_url
                and (
                    url.scheme != "https"
                    or url.hostname not in {"pexels.com", "www.pexels.com"}
                    or url.username
                    or url.password
                    or not url.path.startswith("/photo/")
                )
            )
        ):
            raise ValidationError(
                "Prototype Pexels imports require verified labels, Pexels attribution and Pexels License; any supplied photo URL must be valid."
            )
        return
    if (
        meta.get("metadata_verified") is not True
        or meta.get("label_verified") is not True
        or not known(meta.get("photographer", ""))
        or not known(image.license)
        or not known(image.attribution)
        or not known(image.canonical_answer)
        or url.scheme != "https"
        or url.hostname not in {"pexels.com", "www.pexels.com"}
        or url.username
        or url.password
        or not url.path.startswith("/photo/")
    ):
        raise ValidationError(
            "Local Pexels import requires verified labels, photographer, photo-page URL and license before approval."
        )


class LocalSubmissionSerializer(SubmissionSerializer):
    def validate_image_file(self, upload):
        self.converted = convert_image(upload, resize=True, jpeg_only=True)
        return self.converted.file


def metadata(row):
    difficulty = row["difficulty"].strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        raise ValueError("Difficulty must be easy, medium or hard.")
    synonyms = json.loads(row["accepted_synonyms"] or "[]")
    category = Category.objects.get(slug=row["category"].strip())
    data = {
        "canonical_answer": row["canonical_answer"].strip(),
        "accepted_synonyms": synonyms,
        "category": category.pk,
        "source": "manual",
        "source_url": row["pexels_source_url"].strip(),
        "license": PROTOTYPE_LICENSE
        if settings.PEXELS_PROTOTYPE_METADATA
        else row["license"].strip() or UNVERIFIED,
        "attribution": PROTOTYPE_ATTRIBUTION
        if settings.PEXELS_PROTOTYPE_METADATA
        else row["photographer"].strip() or UNVERIFIED,
    }
    meta = {
        "original_filename": row["original_filename"],
        "source_sha256": row["sha256"],
        "description": row["description"].strip(),
        "difficulty": difficulty,
        "photographer": row["photographer"].strip(),
        "review_notes": row["review_notes"].strip(),
        "label_verified": verified(row["label_verified"]),
        "metadata_verified": verified(row["metadata_verified"]),
        "prototype_metadata": settings.PEXELS_PROTOTYPE_METADATA,
    }
    return data, meta


def verify_stored(image):
    storage = image.image_file.storage
    if not image.image_file.name or not storage.exists(image.image_file.name):
        raise ValueError("Database reference has no stored private image.")
    with storage.open(image.image_file.name, "rb") as file:
        content = file.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != image.local_import_metadata.get("stored_sha256"):
        raise ValueError("Stored WebP checksum differs from the import record.")
    from io import BytesIO

    with Image.open(BytesIO(content)) as decoded:
        decoded.load()
        if (
            decoded.format != "WEBP"
            or min(decoded.size) < 64
            or max(decoded.size) > 4096
            or decoded.width * decoded.height > 12_000_000
            or len(content) > 8 * 1024 * 1024
        ):
            raise ValueError("Stored WebP failed library validation.")
        return len(content), decoded.size


def import_image(row, path, owner, *, cleanup_error):
    """One database transaction per image; file cleanup also covers commit failures."""
    data, meta = metadata(row)
    with path.open("rb") as source:
        from django.core.files import File

        serializer = LocalSubmissionSerializer(
            data={**data, "image_file": File(source, name=path.name)}
        )
        serializer.is_valid(raise_exception=True)
    return register_image(
        row,
        serializer.validated_data,
        meta,
        serializer.converted,
        owner,
        cleanup_error=cleanup_error,
    )


def register_image(row, values, meta, converted, owner, *, cleanup_error):
    row["content_sha256"] = converted.digest
    storage = ImageSubmission._meta.get_field("image_file").storage
    stored = proposed = None
    attempted = False
    try:
        with transaction.atomic():
            # SQLite ignores SELECT FOR UPDATE: serialize pending updates with an UPDATE first.
            ImageSubmission.objects.filter(local_import_digest=converted.digest).update(
                status=F("status")
            )
            image = ImageSubmission.objects.filter(local_import_digest=converted.digest).first()
            if image:
                verify_stored(image)
                if image.status != ImageSubmission.Status.PENDING:
                    return "reviewed_unchanged", image, converted
                if image.local_import_metadata["original_filename"] != row["original_filename"]:
                    return "duplicate", image, converted
                meta["stored_sha256"] = image.local_import_metadata["stored_sha256"]
                values = {k: v for k, v in values.items() if k != "image_file"}
                changes = [key for key, value in values.items() if getattr(image, key) != value]
                for key in changes:
                    setattr(image, key, values[key])
                if image.local_import_metadata != meta:
                    image.local_import_metadata = meta
                    changes.append("local_import_metadata")
                if changes:
                    image.full_clean()
                    image.save(update_fields=changes)
                return "updated_pending" if changes else "duplicate", image, converted
            image = ImageSubmission(
                **{k: v for k, v in values.items() if k != "image_file"},
                submitted_by=owner,
                local_import_digest=converted.digest,
                local_import_metadata=meta,
            )
            field = image._meta.get_field("image_file")
            proposed = field.generate_filename(image, "image.webp")
            while storage.exists(proposed):
                proposed = field.generate_filename(image, "image.webp")
            image.image_file.name = proposed
            converted.file.seek(0)
            meta["stored_sha256"] = hashlib.sha256(converted.file.read()).hexdigest()
            converted.file.seek(0)
            image.full_clean()
            attempted = True
            stored = storage.save(proposed, converted.file, max_length=field.max_length)
            image.image_file.name = stored
            verify_stored(image)
            image.save(force_insert=True)
        return "imported_pending", image, converted
    except Exception as failure:
        # A storage backend may write a partial file before raising from save().
        if attempted:
            try:
                storage.delete(stored or proposed)
            except Exception as exc:
                message = (
                    f"{failure}; cleanup failed for private storage key {stored or proposed}: {exc}"
                )
                cleanup_error(message)
                raise RuntimeError(message) from failure
        raise


def record_result(row, image):
    size, dimensions = verify_stored(image)
    row.update(
        {
            "image_id": str(image.pk),
            "storage_name": image.image_file.name,
            "stored_sha256": image.local_import_metadata["stored_sha256"],
            "content_sha256": image.local_import_digest,
            "width": str(dimensions[0]),
            "height": str(dimensions[1]),
        }
    )
    return size


def manifest_image(row):
    image = ImageSubmission.objects.get(
        pk=row["image_id"], local_import_digest=row["content_sha256"]
    )
    if (
        image.image_file.name != row["storage_name"]
        or image.local_import_metadata.get("stored_sha256") != row["stored_sha256"]
    ):
        raise ValueError("Manifest storage reference differs from the database.")
    verify_stored(image)
    return image


class StoredSubmissionSerializer(SubmissionSerializer):
    def validate_image_file(self, upload):
        # Only used after verify_stored(), never by an HTTP upload endpoint.
        return upload


def update_metadata(row):
    """Manifest corrections need only private storage, never the original JPEG."""
    with transaction.atomic():
        ImageSubmission.objects.filter(pk=row["image_id"]).update(status=F("status"))
        image = manifest_image(row)
        if image.status != ImageSubmission.Status.PENDING:
            return "reviewed_unchanged", image
        data, meta = metadata(row)
        with image.image_file.storage.open(image.image_file.name, "rb") as file:
            serializer = StoredSubmissionSerializer(data={**data, "image_file": file})
            serializer.is_valid(raise_exception=True)
        for key in ("original_filename", "source_sha256", "stored_sha256"):
            meta[key] = image.local_import_metadata[key]
        values = {k: v for k, v in serializer.validated_data.items() if k != "image_file"}
        changes = [key for key, value in values.items() if getattr(image, key) != value]
        for key in changes:
            setattr(image, key, values[key])
        if image.local_import_metadata != meta:
            image.local_import_metadata = meta
            changes.append("local_import_metadata")
        if changes:
            image.full_clean()
            image.save(update_fields=changes)
        return "updated_pending" if changes else "duplicate", image
