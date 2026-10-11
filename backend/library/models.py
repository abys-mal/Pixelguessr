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
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="image_submissions"
    )
    canonical_answer = models.CharField(max_length=120)
    accepted_synonyms = models.JSONField(default=list, validators=[validate_synonyms])
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
        on_delete=models.PROTECT,
        related_name="images_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
                | models.Q(reviewed_at__isnull=False, reviewed_by__isnull=False),
                name="image_review_required",
            ),
        ]

    def clean(self):
        if bool(self.image_file) == bool(self.external_image_url):
            raise ValidationError("Provide exactly one uploaded image or external reference.")
        if self.status != self.Status.PENDING and (not self.reviewed_by_id or not self.reviewed_at):
            raise ValidationError("Reviewed submissions require a reviewer and timestamp.")
        if self.reviewed_by_id and not self.reviewed_by.is_staff:
            raise ValidationError({"reviewed_by": "Approval requires staff authorization."})
