import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Category(models.TextChoices):
    FAIR_PLAY = "fair_play", "Fair Play"
    SPORTSMANSHIP = "sportsmanship", "Sportsmanship and Community Guidelines"
    INTEGRITY = "integrity", "Platform Integrity"


class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_filed"
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_received"
    )
    category = models.CharField(max_length=20, choices=Category)
    details = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["resolved_at", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(reporter=models.F("subject")), name="report_not_self"
            )
        ]


class Sanction(models.Model):
    class Kind(models.TextChoices):
        WARNING = "warning", "Warning"
        PROBATION = "probation", "Probation"
        SUSPENSION = "suspension", "Suspension"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sanctions"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sanctions_issued"
    )
    category = models.CharField(max_length=20, choices=Category)
    kind = models.CharField(max_length=12, choices=Kind)
    reason = models.TextField(max_length=2000)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sanctions_revoked",
    )

    class Meta:
        indexes = [models.Index(fields=["user", "kind", "revoked_at", "expires_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("starts_at")),
                name="sanction_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="warning") | models.Q(expires_at__isnull=False),
                name="warning_must_expire",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="closed") | models.Q(expires_at__isnull=True),
                name="closure_is_permanent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True, revoked_by__isnull=True)
                    | models.Q(revoked_at__isnull=False, revoked_by__isnull=False)
                ),
                name="sanction_revocation_audited",
            ),
        ]

    def clean(self):
        if self.kind == self.Kind.WARNING:
            self.expires_at = self.starts_at + timedelta(days=90)
        if self.kind == self.Kind.CLOSED and self.expires_at:
            raise ValidationError({"expires_at": "Account closure has no expiry."})
        original = (
            type(self)
            .objects.using(self._state.db or "default")
            .filter(pk=self.pk)
            .values("issued_by_id", "revoked_by_id", "revoked_at")
            .first()
            if not self._state.adding
            else None
        )
        # Authorization belongs to the action time; later role removal preserves history.
        issuer_changed = original is None or original["issued_by_id"] != self.issued_by_id
        revocation_changed = (
            original is None
            or original["revoked_by_id"] != self.revoked_by_id
            or original["revoked_at"] != self.revoked_at
        )
        if issuer_changed and self.issued_by_id and not self.issued_by.is_staff:
            raise ValidationError({"issued_by": "Sanctions require staff authorization."})
        if revocation_changed and self.revoked_by_id:
            if not self.revoked_by.is_staff:
                raise ValidationError({"revoked_by": "Revocation requires staff authorization."})
            if self.kind == self.Kind.CLOSED and not self.revoked_by.is_superuser:
                raise ValidationError({"revoked_by": "Only administrators can reverse closure."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
