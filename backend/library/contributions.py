"""One image record per contribution; private history with content-free removal receipts."""

from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from .file_cleanup import drain_file_deletions
from .models import ImageSubmission, PendingFileDeletion, RemovedContribution


def contribution_data(image, *, staff=False):
    data = {
        "id": str(image.pk),
        "status": image.status,
        "created_at": image.created_at,
        "canonical_answer": image.canonical_answer,
        "accepted_synonyms": image.accepted_synonyms,
        "category": image.category_id,
        "category_name": image.category.name,
        "source": image.source,
        "source_url": image.source_url,
        "license": image.license,
        "attribution": image.attribution,
        "retired": bool(image.retired_at),
        "explanation": image.player_review_explanation,
        "preview_url": f"/api/library/contributions/{image.pk}/preview/"
        if image.image_file
        else None,
    }
    if staff:
        data.update(
            {
                "submitter": image.submitted_by.username
                if image.submitted_by
                else "Deleted player",
                "submitter_id": str(image.submitted_by_id) if image.submitted_by_id else None,
                "rights_acknowledged_at": image.rights_acknowledged_at,
            }
        )
    return data


def receipt_data(receipt, *, staff=False):
    data = {"id": str(receipt.pk), "status": "removed", "created_at": receipt.created_at}
    if staff:
        data.update(
            {
                "submitter": receipt.submitted_by.username
                if receipt.submitted_by
                else "Deleted player",
                "submitter_id": str(receipt.submitted_by_id) if receipt.submitted_by_id else None,
            }
        )
    return data


def history_rows(images, receipts, *, prioritize=False):
    fields = ["id", "created_at", "status"]
    receipts = receipts.annotate(status=Value("removed"))
    order = ["-created_at", "id"]
    if prioritize:
        priority = Case(
            When(status="pending", then=Value(0)), default=Value(1), output_field=IntegerField()
        )
        images = images.annotate(priority=priority)
        receipts = receipts.annotate(priority=priority)
        fields.append("priority")
        order.insert(0, "priority")
    return (
        images.order_by()
        .values(*fields)
        .union(receipts.order_by().values(*fields))
        .order_by(*order)
    )


def history_item(pk, user, *, staff=False):
    images = ImageSubmission.objects.filter(player_contribution=True).select_related(
        "category", "submitted_by"
    )
    receipts = RemovedContribution.objects.select_related("submitted_by")
    if not staff:
        images = images.filter(submitted_by=user)
        receipts = receipts.filter(submitted_by=user)
    image = images.filter(pk=pk).first()
    return (
        contribution_data(image, staff=staff)
        if image
        else receipt_data(get_object_or_404(receipts, pk=pk), staff=staff)
    )


def schedule_cleanup(name):
    job, _ = PendingFileDeletion.objects.get_or_create(name=name)
    if job.completed_at:
        job.completed_at = None
        job.save(update_fields=["completed_at"])
    transaction.on_commit(lambda: drain_file_deletions([job.pk]), robust=True)


def create_contribution(actor, data):
    from moderation.administration import audit
    from moderation.services import account_restrictions, require_warning_acknowledgment
    from moderation.workspace import lock_player

    values = dict(data)
    values.pop("rights_acknowledged")
    upload = values.pop("image_file")
    image = ImageSubmission(
        **values,
        submitted_by=actor,
        player_contribution=True,
        rights_acknowledged_at=timezone.now(),
    )
    storage = image.image_file.storage
    name = proposed = None
    try:
        with transaction.atomic():
            owner = lock_player(actor.pk)
            require_warning_acknowledgment(owner)
            restrictions = account_restrictions(owner)
            if restrictions["blocked"] or restrictions["suspension"] or restrictions["probation"]:
                raise PermissionDenied("Image submissions are unavailable for this account.")
            proposed = image.image_file.field.generate_filename(image, "image.webp")
            name = storage.save(proposed, upload)
            image.image_file = name
            image.full_clean()
            image.save()
            audit(
                owner, "image_submitted", ("image", image.pk), {}, {"status": "pending"}, user=owner
            )
    except Exception:
        if name or proposed:
            schedule_cleanup(name or proposed)
        raise
    return image
