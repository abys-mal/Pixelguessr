import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def private_image_path(instance, filename):
    # Never retain a filename that could contain the answer.
    return f"images/{uuid.uuid4().hex}.webp"


def validate_synonyms(value):
    if (
        not isinstance(value, list)
        or len(value) > 30
        or any(not isinstance(item, str) or not item.strip() or len(item) > 120 for item in value)
    ):
        raise ValidationError("Provide at most 30 nonempty synonyms, each up to 120 characters.")


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class ImageSubmission(models.Model):
    class Source(models.TextChoices):
        COMMONS = "commons", "Wikimedia Commons"
        LICENSED = "licensed", "Other licensed source"
        AI = "ai", "AI-generated"
        MANUAL = "manual", "Manual upload"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="image_submissions",
        null=True,
        blank=True,
    )
    canonical_answer = models.CharField(max_length=120)
    accepted_synonyms = models.JSONField(default=list, blank=True, validators=[validate_synonyms])
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    source = models.CharField(max_length=12, choices=Source)
    source_url = models.URLField(max_length=1000, blank=True)
    external_image_url = models.URLField(max_length=1000, blank=True)
    image_file = models.FileField(upload_to=private_image_path, blank=True)
    license = models.CharField(max_length=160)
    attribution = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=Status, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="images_reviewed",
    )
    reviewer_deleted = models.BooleanField(default=False, editable=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Private import provenance; never accepted or emitted by the public serializers.
    local_import_digest = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    local_import_metadata = models.JSONField(default=dict, blank=True, editable=False)
    retired_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="images_retired",
    )
    review_reason = models.TextField(max_length=2000, blank=True)
    player_contribution = models.BooleanField(default=False, editable=False, db_index=True)
    rights_acknowledged_at = models.DateTimeField(null=True, blank=True, editable=False)
    player_review_explanation = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "category", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(image_file="") & ~models.Q(external_image_url=""))
                | (~models.Q(image_file="") & models.Q(external_image_url="")),
                name="image_exactly_one_reference",
            ),
            models.CheckConstraint(
                condition=models.Q(status="pending")
                | (
                    models.Q(reviewed_at__isnull=False)
                    & (models.Q(reviewed_by__isnull=False) | models.Q(reviewer_deleted=True))
                ),
                name="image_review_required",
            ),
        ]

    def clean(self):
        try:
            validate_synonyms(self.accepted_synonyms)
        except ValidationError as exc:
            raise ValidationError({"accepted_synonyms": exc.messages}) from exc
        if bool(self.image_file) == bool(self.external_image_url):
            raise ValidationError("Provide exactly one uploaded image or external reference.")
        historical_review = (
            not self._state.adding
            and type(self)
            .objects.filter(
                pk=self.pk,
                status=self.status,
                reviewed_at=self.reviewed_at,
                reviewed_by__isnull=True,
                reviewer_deleted=True,
            )
            .exists()
        )
        if self.status != self.Status.PENDING and (
            not self.reviewed_at or (not self.reviewed_by_id and not historical_review)
        ):
            raise ValidationError("Reviewed submissions require a reviewer and timestamp.")
        if self.reviewed_by_id and not self.reviewed_by.is_staff:
            raise ValidationError({"reviewed_by": "Approval requires staff authorization."})
        if self.local_import_digest and self.status == self.Status.APPROVED:
            from .local_import import validate_approval

            validate_approval(self)


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ImportItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="items")
    request_id = models.UUIDField(unique=True)
    filename = models.CharField(max_length=255)
    image = models.ForeignKey(ImageSubmission, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=16,
        choices=[("uploaded", "Uploaded"), ("duplicate", "Duplicate"), ("failed", "Failed")],
    )
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PendingFileDeletion(models.Model):
    """Durable post-commit cleanup, without account identifiers or credentials."""

    name = models.CharField(max_length=500, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=160, blank=True)


class RemovedContribution(models.Model):
    """Content-free receipt; identity and original time only. Account erasure cascades."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at", "id"]
