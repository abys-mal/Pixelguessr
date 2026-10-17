"""The staff-review operation shared by Admin and explicit development imports."""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import ImageSubmission


def review_images(queryset, reviewer, status):
    if not reviewer.is_staff:
        raise PermissionDenied("Image review requires staff authorization.")
    if status not in {ImageSubmission.Status.APPROVED, ImageSubmission.Status.REJECTED}:
        raise ValueError("Choose approved or rejected.")
    with transaction.atomic():
        for image in queryset:
            image.status = status
            image.reviewed_by = reviewer
            image.reviewer_deleted = False
            image.reviewed_at = timezone.now()
            image.full_clean()
            image.save(update_fields=["status", "reviewed_by", "reviewed_at", "reviewer_deleted"])
