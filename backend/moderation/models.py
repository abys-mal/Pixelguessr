import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone


class IPAccessEntry(models.Model):
    class ListKind(models.TextChoices):
        BLACKLIST = "blacklist", "Blacklist"
        WHITELIST = "whitelist", "Whitelist"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    list_kind = models.CharField(max_length=10, choices=ListKind)
    address = models.GenericIPAddressField(unpack_ipv4=True)
    reason = models.TextField(max_length=2000)
    block_registration = models.BooleanField(default=False)
    block_login = models.BooleanField(default=False)
    block_singleplayer = models.BooleanField(default=False)
    block_parties = models.BooleanField(default=False)
    block_ranked = models.BooleanField(default=False)
    block_submissions = models.BooleanField(default=False)
    block_community = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["list_kind", "address"], name="unique_ip_per_access_list"
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("created_at")),
                name="ip_expiry_after_creation",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(list_kind="blacklist")
                    & (
                        models.Q(block_registration=True)
                        | models.Q(block_login=True)
                        | models.Q(block_singleplayer=True)
                        | models.Q(block_parties=True)
                        | models.Q(block_ranked=True)
                        | models.Q(block_submissions=True)
                        | models.Q(block_community=True)
                    )
                )
                | (
                    models.Q(
                        list_kind="whitelist",
                        expires_at__isnull=True,
                        block_registration=False,
                        block_login=False,
                        block_singleplayer=False,
                        block_parties=False,
                        block_ranked=False,
                        block_submissions=False,
                        block_community=False,
                    )
                ),
                name="ip_access_list_configuration",
            ),
        ]

    @property
    def activities(self):
        from .ip_rules import ACTIVITIES

        return [activity for activity in ACTIVITIES if getattr(self, "block_" + activity)]

    def clean(self):
        from core.client_ip import ClientIPError, normalize_ip

        try:
            self.address = normalize_ip(self.address)
        except ClientIPError as exc:
            raise ValidationError({"address": str(exc)}) from exc
        if not self.reason.strip():
            raise ValidationError({"reason": "An internal reason is required."})
        if self.list_kind == "blacklist" and not self.activities:
            raise ValidationError({"activities": "Select at least one activity."})
        if self.list_kind == "whitelist" and (self.activities or self.expires_at):
            raise ValidationError("Whitelist entries cannot have restrictions or an expiration.")

    def save(self, *args, **kwargs):
        from core.client_ip import normalize_ip

        self.address = normalize_ip(self.address)
        return super().save(*args, **kwargs)


class Category(models.TextChoices):
    FAIR_PLAY = "fair_play", "Fair Play"
    SPORTSMANSHIP = "sportsmanship", "Sportsmanship and Community Guidelines"
    INTEGRITY = "integrity", "Platform Integrity"
    OTHER = "other", "Other"


class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reports_filed",
        null=True,
        blank=True,
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reports_received"
    )
    category = models.CharField(max_length=20, choices=Category)
    details = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(
        max_length=12, blank=True, choices=[("resolved", "Resolved"), ("dismissed", "Dismissed")]
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports_resolved",
    )

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
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="sanctions_issued",
        null=True,
        blank=True,
    )
    origin = models.CharField(
        max_length=16,
        choices=[("disciplinary", "Disciplinary"), ("voluntary", "Voluntary closure")],
        default="disciplinary",
        editable=False,
    )
    category = models.CharField(max_length=20, choices=Category)
    kind = models.CharField(max_length=12, choices=Kind)
    reason = models.TextField(max_length=2000, blank=True)
    internal_note = models.TextField(max_length=2000, blank=True)
    replaces = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacement"
    )
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    revoker_deleted = models.BooleanField(default=False, editable=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sanctions_revoked",
    )

    class Meta:
        permissions = [("access_workspace", "Access native moderation workspace")]
        indexes = [models.Index(fields=["user", "kind", "revoked_at", "expires_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("starts_at")),
                name="sanction_expiry_after_start",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="warning")
                | models.Q(acknowledged_at__isnull=True)
                | models.Q(
                    expires_at__isnull=False,
                    expires_at=models.F("acknowledged_at") + timedelta(days=90),
                ),
                name="warning_expiry_after_acknowledgment",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="closed") | models.Q(expires_at__isnull=True),
                name="closure_is_permanent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True, revoked_by__isnull=True)
                    | (
                        models.Q(revoked_at__isnull=False)
                        & (models.Q(revoked_by__isnull=False) | models.Q(revoker_deleted=True))
                    )
                ),
                name="sanction_revocation_audited",
            ),
        ]

    def clean(self):
        voluntary = self.origin == "voluntary"
        if voluntary and (self.kind != "closed" or self.user_id != self.issued_by_id):
            raise ValidationError("Voluntary closure must be initiated by its account owner.")
        if self.kind == self.Kind.CLOSED and self.expires_at:
            raise ValidationError({"expires_at": "Account closure has no expiry."})
        if (
            self._state.adding
            and self.user_id
            and self.starts_at
            and self.kind != self.Kind.WARNING
            and not self.revoked_at
        ):
            overlap = (
                type(self)
                .objects.filter(user_id=self.user_id, kind=self.kind, revoked_at__isnull=True)
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=self.starts_at))
            )
            if overlap.exists():
                raise ValidationError(
                    "An active or scheduled sanction of this type already exists. Replace it instead."
                )
        imposition_fields = ("user_id", "issued_by_id", "kind", "starts_at", "expires_at", "origin")
        original = (
            type(self)
            .objects.using(self._state.db or "default")
            .filter(pk=self.pk)
            .values(*imposition_fields, "revoked_by_id", "revoked_at", "acknowledged_at")
            .first()
            if not self._state.adding
            else None
        )
        if self.kind == self.Kind.WARNING:
            if self.acknowledged_at:
                self.expires_at = self.acknowledged_at + timedelta(days=90)
            elif (
                original
                and original["kind"] == self.Kind.WARNING
                and not original["acknowledged_at"]
                and (
                    original["revoked_at"]
                    or (original["expires_at"] and original["expires_at"] <= timezone.now())
                )
            ):
                # Preserve persisted inactive history, not a newly supplied expiry.
                self.expires_at = original["expires_at"]
            else:
                self.expires_at = None
        # Authorization belongs to the action time; later role removal preserves history.
        issuer_changed = original is None or original["issued_by_id"] != self.issued_by_id
        revocation_changed = (
            original is None
            or original["revoked_by_id"] != self.revoked_by_id
            or original["revoked_at"] != self.revoked_at
        )
        from .permissions import is_moderator, validate_sanction_target

        imposition_changed = (
            original is None
            or any(original[field] != getattr(self, field) for field in imposition_fields)
            or (original["revoked_at"] is not None and self.revoked_at is None)
        )
        if imposition_changed and not voluntary and self.issued_by_id and self.user_id:
            from accounts.models import User

            # Fresh identities avoid stale role caches at the authoritative save boundary.
            validate_sanction_target(
                User.objects.get(pk=self.issued_by_id), User.objects.get(pk=self.user_id)
            )

        if (
            issuer_changed
            and not voluntary
            and self.issued_by_id
            and not (self.issued_by.is_staff or is_moderator(self.issued_by))
        ):
            raise ValidationError({"issued_by": "Sanctions require staff authorization."})
        if revocation_changed and self.revoked_at and not self.revoked_by_id:
            raise ValidationError({"revoked_by": "A new revocation requires an actor."})
        if revocation_changed and self.revoked_by_id:
            if not (self.revoked_by.is_staff or is_moderator(self.revoked_by)):
                raise ValidationError({"revoked_by": "Revocation requires staff authorization."})
            if self.kind == self.Kind.CLOSED and not self.revoked_by.is_superuser:
                raise ValidationError({"revoked_by": "Only administrators can reverse closure."})

    def save(self, *args, **kwargs):
        from accounts.models import User

        with transaction.atomic(using=kwargs.get("using") or self._state.db or "default"):
            from games.ranked import gate

            gate()
            # First write serializes per-player decisions on SQLite and PostgreSQL.
            User.objects.filter(pk=self.user_id).update(
                last_username_change=F("last_username_change")
            )
            original = (
                type(self).objects.filter(pk=self.pk).first() if not self._state.adding else None
            )
            self.full_clean()
            super().save(*args, **kwargs)
            if original is None:
                Activity.objects.create(
                    user_id=self.user_id,
                    actor_id=self.issued_by_id,
                    action="voluntary_closure"
                    if self.origin == "voluntary"
                    else "sanction_replaced"
                    if self.replaces_id
                    else "sanction_issued",
                    sanction=self,
                    changes={
                        "kind": self.kind,
                        "origin": self.origin,
                        "category": self.category,
                        "reason": self.reason,
                        "internal_note": self.internal_note,
                        "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                        "replaces": str(self.replaces_id) if self.replaces_id else None,
                    },
                )
            elif not original.revoked_at and self.revoked_at:
                Activity.objects.create(
                    user_id=self.user_id,
                    actor_id=self.revoked_by_id,
                    action="sanction_reversed",
                    sanction=self,
                    changes={"kind": self.kind},
                )
                for appeal in self.appeals.filter(status=Appeal.Status.PENDING):
                    appeal.status = Appeal.Status.CHANGED
                    appeal.resolved_at = self.revoked_at
                    appeal.resolved_by_id = self.revoked_by_id
                    appeal.save(update_fields=["status", "resolved_at", "resolved_by"])
                    Activity.objects.create(
                        user_id=self.user_id,
                        actor_id=self.revoked_by_id,
                        action="appeal_sanction_changed",
                        sanction=self,
                        appeal=appeal,
                    )
            from .enforcement import enforce_locked, schedule

            enforce_locked(self.user_id)

            schedule(self.user_id)


class Appeal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        UPHELD = "upheld", "Upheld"
        REVERSED = "reversed", "Sanction reversed"
        CHANGED = "sanction_changed", "Sanction changed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="appeals"
    )
    sanction = models.ForeignKey(Sanction, on_delete=models.PROTECT, related_name="appeals")
    kind = models.CharField(max_length=12, choices=Sanction.Kind)
    explanation = models.TextField(max_length=4000)
    closing_reason = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=20, choices=Status, default=Status.PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appeals_resolved",
    )

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sanction"], condition=Q(kind="warning"), name="one_appeal_per_warning"
            ),
            models.UniqueConstraint(
                fields=["user", "kind"],
                condition=Q(status="pending", kind__in=["probation", "suspension"]),
                name="one_pending_appeal_per_type",
            ),
        ]


class Activity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="moderation_activity",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="moderation_actions",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=40)
    created_at = models.DateTimeField(default=timezone.now)
    sanction = models.ForeignKey(Sanction, null=True, blank=True, on_delete=models.SET_NULL)
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.SET_NULL)
    appeal = models.ForeignKey(Appeal, null=True, blank=True, on_delete=models.SET_NULL)
    changes = models.JSONField(default=dict, blank=True)
    target_type = models.CharField(max_length=32, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    reason = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["action", "created_at"])]


class StaffAnnouncement(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    title = models.CharField(max_length=160, blank=True)
    body = models.TextField(max_length=5000, blank=True)
    published = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    editor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    version = models.PositiveIntegerField(default=0)
