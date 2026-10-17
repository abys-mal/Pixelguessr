import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from games.ranked_rules import starting_rating


class User(AbstractUser):
    class Tier(models.TextChoices):
        UNRANKED = "unranked", "Unranked"
        BRONZE = "bronze", "Bronze"
        SILVER = "silver", "Silver"
        GOLD = "gold", "Gold"
        DIAMOND = "diamond", "Diamond"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    last_username_change = models.DateTimeField(default=timezone.now, editable=False)
    display_name = models.CharField(max_length=40, blank=True)
    rating = models.PositiveIntegerField(default=starting_rating, db_index=True)
    ranked_matches = models.PositiveIntegerField(default=0)
    ranked_wins = models.PositiveIntegerField(default=0)
    ranked_losses = models.PositiveIntegerField(default=0)
    # Legacy column retained for compatibility; API tiers are derived from rating.
    ranked_tier = models.CharField(max_length=12, choices=Tier, default=Tier.UNRANKED)

    def save(self, *args, **kwargs):
        if self._state.adding:
            # Account creation is the initial assignment, including trusted creation.
            self.last_username_change = self.date_joined
        super().save(*args, **kwargs)

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
        User, on_delete=models.SET_NULL, related_name="title_verifications", null=True, blank=True
    )
    verified_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        previous = (
            type(self)
            .objects.using(self._state.db or "default")
            .filter(pk=self.pk)
            .values("verified_by_id")
            .first()
            if not self._state.adding
            else None
        )
        verifier_changed = previous is None or previous["verified_by_id"] != self.verified_by_id
        if verifier_changed and self.verified_by_id and not self.verified_by.is_staff:
            raise ValidationError({"verified_by": "Verification requires a staff member."})
