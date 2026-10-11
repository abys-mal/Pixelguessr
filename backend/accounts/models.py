import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    class Tier(models.TextChoices):
        UNRANKED = "unranked", "Unranked"
        BRONZE = "bronze", "Bronze"
        SILVER = "silver", "Silver"
        GOLD = "gold", "Gold"
        DIAMOND = "diamond", "Diamond"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=40, blank=True)
    # Initial rating is provisional. No tier thresholds or Elo calculation in Phase 1.
    rating = models.PositiveIntegerField(default=1000)
    ranked_tier = models.CharField(max_length=12, choices=Tier, default=Tier.UNRANKED)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("username"), name="user_username_ci_unique"),
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]


class VerifiedTitle(models.Model):
    class Title(models.TextChoices):
        PRO = "pro", "Pro"
        MASTER = "master", "Master"
        LEGEND = "legend", "Legend"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="verified_title")
    title = models.CharField(max_length=10, choices=Title)
    verified_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="title_verifications"
    )
    verified_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.verified_by_id and not self.verified_by.is_staff:
            raise ValidationError({"verified_by": "Verification requires a staff member."})
