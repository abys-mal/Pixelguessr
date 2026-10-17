"""Retryable file cleanup runs only after database commit and rechecks shared references."""

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from games.models import Round

from .models import ImageSubmission, PendingFileDeletion


def drain_file_deletions(ids=None, limit=100):
    rows = PendingFileDeletion.objects.filter(completed_at__isnull=True).order_by("pk")
    if ids is not None:
        rows = rows.filter(pk__in=ids)
    completed = failed = 0
    for pk in list(rows.values_list("pk", flat=True)[:limit]):
        with transaction.atomic():
            PendingFileDeletion.objects.filter(pk=pk).update(attempts=F("attempts") + 1)
            job = PendingFileDeletion.objects.get(pk=pk)
            if job.completed_at:
                continue
            if (
                ImageSubmission.objects.filter(image_file=job.name).exists()
                or Round.objects.filter(image_storage_name=job.name).exists()
            ):
                job.completed_at = timezone.now()
                job.last_error = "Shared file retained."
            else:
                try:
                    default_storage.delete(job.name)
                except Exception:
                    job.last_error = (
                        "Private storage cleanup failed; retry with cleanup_deleted_files."
                    )
                    failed += 1
                else:
                    job.completed_at = timezone.now()
                    job.last_error = ""
            job.save(update_fields=["completed_at", "last_error"])
            completed += bool(job.completed_at)
    return {"completed": completed, "failed": failed}
