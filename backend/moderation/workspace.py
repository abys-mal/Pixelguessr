"""Native moderation commands share a durable per-player writer lock."""

from datetime import timedelta

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User

from .models import Activity, Appeal, Report, Sanction
from .permissions import is_administrator, is_moderator, is_protected, validate_sanction_target
from .services import account_restrictions, active_sanctions


def lock_player(pk):
    from games.ranked import gate

    gate()
    User.objects.filter(pk=pk).update(last_username_change=F("last_username_change"))
    return get_object_or_404(User, pk=pk)


def authorize(actor, target, *, closure=False, imposing=False):
    actor = User.objects.get(pk=actor.pk)  # No stale permission cache from the request.
    if not is_moderator(actor) or account_restrictions(actor)["blocked"]:
        raise PermissionDenied("Moderator access is required.")
    if imposing:
        try:
            validate_sanction_target(actor, target)
        except ModelValidationError as exc:
            raise PermissionDenied(exc.messages[0]) from exc
    if not is_administrator(actor) and (is_protected(target) or closure):
        raise PermissionDenied("This action requires an administrator.")


def eligibility(user, sanction):
    now = timezone.now()
    if not active_sanctions(user).filter(pk=sanction.pk).exists():
        return {
            "eligible": False,
            "detail": "This sanction is no longer active.",
            "available_at": None,
        }
    if sanction.kind == "closed":
        return {
            "eligible": False,
            "detail": "Account closure cannot be appealed.",
            "available_at": None,
        }
    if sanction.kind == "warning":
        if sanction.appeals.exists():
            return {
                "eligible": False,
                "detail": "This warning has already been appealed.",
                "available_at": None,
            }
    else:
        upheld = (
            user.appeals.filter(
                kind=sanction.kind, status=Appeal.Status.UPHELD, resolved_at__isnull=False
            )
            .order_by("-resolved_at", "-id")
            .first()
        )
        available = (
            upheld.resolved_at + timedelta(days=30 if sanction.kind == "probation" else 90)
            if upheld
            else None
        )
        cooling_down = available is not None and now < available
        if user.appeals.filter(kind=sanction.kind, status=Appeal.Status.PENDING).exists():
            return {
                "eligible": False,
                "detail": "An appeal of this type is already pending.",
                "available_at": available.isoformat() if cooling_down else None,
            }
        if cooling_down:
            return {
                "eligible": False,
                "detail": "The appeal cooldown has not ended since the last upheld decision.",
                "available_at": available.isoformat(),
            }
    return {"eligible": True, "detail": "You can appeal this sanction.", "available_at": None}


def _reverse(actor, sanction):
    if sanction.kind == Sanction.Kind.CLOSED:
        raise ValidationError({"detail": "Use Administrator Controls to reopen a closed account."})
    _record_reversal(actor, sanction)


def _record_reversal(actor, sanction):
    """Persist an authorized reversal; reopening authorizes in Administrator Controls."""
    sanction.revoked_at = timezone.now()
    sanction.revoked_by = actor
    sanction.save(update_fields=["revoked_at", "revoked_by"])


@transaction.atomic
def issue(actor, user_id, data, *, replacing=None):
    target = lock_player(user_id)
    authorize(actor, target, imposing=True)
    original = None
    if replacing:
        original = get_object_or_404(active_sanctions(target), pk=replacing)
        authorize(actor, target, closure=original.kind == "closed")
    try:
        if original:
            _reverse(actor, original)
        sanction = Sanction(user=target, issued_by=actor, replaces=original, **data)
        sanction.save()
    except ModelValidationError as exc:
        raise ValidationError({"detail": exc.messages}) from exc
    return sanction


def reverse(actor, sanction_id):
    snapshot = get_object_or_404(Sanction, pk=sanction_id)
    return _reverse_locked(actor, sanction_id, snapshot.user_id)


@transaction.atomic
def _reverse_locked(actor, sanction_id, user_id):
    target = lock_player(user_id)
    sanction = get_object_or_404(active_sanctions(target), pk=sanction_id)
    authorize(actor, target, closure=sanction.kind == "closed")
    _reverse(actor, sanction)
    return sanction


@transaction.atomic
def acknowledge_warning(user, sanction_id):
    # Share the sanction writer lock with reversal/replacement and concurrent retries.
    target = lock_player(user.pk)
    warnings = active_sanctions(target).filter(pk=sanction_id, kind=Sanction.Kind.WARNING)
    now = timezone.now()
    warnings.filter(acknowledged_at__isnull=True).update(
        acknowledged_at=now, expires_at=now + timedelta(days=90)
    )
    sanction = get_object_or_404(warnings)
    from .enforcement import schedule

    schedule(target.pk)
    return sanction


@transaction.atomic
def submit_appeal(user, sanction_id, explanation):
    user = lock_player(user.pk)
    sanction = get_object_or_404(Sanction, user=user, pk=sanction_id)
    allowed = eligibility(user, sanction)
    if not allowed["eligible"]:
        raise ValidationError({"detail": allowed["detail"]})
    appeal = Appeal.objects.create(
        user=user, sanction=sanction, kind=sanction.kind, explanation=explanation
    )
    Activity.objects.create(
        user=user, actor=user, action="appeal_submitted", sanction=sanction, appeal=appeal
    )
    return appeal


def review_appeal(actor, appeal_id, decision, closing_reason=""):
    snapshot = get_object_or_404(Appeal, pk=appeal_id)
    return _review_appeal_locked(actor, appeal_id, decision, snapshot.user_id, closing_reason)


@transaction.atomic
def _review_appeal_locked(actor, appeal_id, decision, user_id, closing_reason=""):
    target = lock_player(user_id)
    authorize(actor, target)
    appeal = Appeal.objects.select_related("sanction").get(pk=appeal_id)
    if appeal.status != "pending":
        raise ValidationError({"detail": "This appeal has already been resolved."})
    if not active_sanctions(target).filter(pk=appeal.sanction_id).exists():
        appeal.status = "sanction_changed"
    else:
        appeal.status = "upheld" if decision == "uphold" else "reversed"
    if decision not in {"uphold", "reverse"}:
        raise ValidationError({"decision": "Unknown appeal decision."})
    if not isinstance(closing_reason, str) or len(closing_reason) > 2000:
        raise ValidationError({"closing_reason": "Use at most 2000 characters."})
    appeal.closing_reason = closing_reason.strip()
    appeal.resolved_at = timezone.now()
    appeal.resolved_by = actor
    appeal.save(update_fields=["status", "resolved_at", "resolved_by", "closing_reason"])
    if appeal.status == "reversed":
        authorize(actor, target, closure=appeal.sanction.kind == "closed")
        _reverse(actor, appeal.sanction)
    Activity.objects.create(
        user=target,
        actor=actor,
        action="appeal_" + appeal.status,
        changes={"closing_reason": appeal.closing_reason},
        appeal=appeal,
        sanction=appeal.sanction,
    )
    return appeal


def resolve_report(actor, report_id, decision):
    snapshot = get_object_or_404(Report, pk=report_id)
    return _resolve_report_locked(actor, report_id, decision, snapshot.subject_id)


@transaction.atomic
def _resolve_report_locked(actor, report_id, decision, user_id):
    target = lock_player(user_id)
    authorize(actor, target)
    report = Report.objects.get(pk=report_id)
    if report.resolved_at:
        raise ValidationError({"detail": "This report has already been resolved."})
    report.resolved_at = timezone.now()
    report.resolved_by = actor
    report.resolution = decision
    report.save(update_fields=["resolved_at", "resolved_by", "resolution"])
    Activity.objects.create(user=target, actor=actor, action="report_" + decision, report=report)
    return report


@transaction.atomic
def change_access(actor, user_id, enabled):
    from django.contrib.auth.models import Group, Permission

    target = lock_player(user_id)
    actor = User.objects.get(pk=actor.pk)
    authorize(actor, target)
    if not is_administrator(actor):
        raise PermissionDenied("Only administrators can manage moderator access.")
    if actor.pk == target.pk or target.is_superuser or target.is_staff:
        raise ValidationError(
            {"detail": "Administrator and legacy staff roles are command-line-only."}
        )
    permission = Permission.objects.get(
        content_type__app_label="moderation", codename="access_workspace"
    )
    before = is_protected(target)
    if before == enabled:
        return
    if enabled:
        target.user_permissions.add(permission)
    else:
        target.user_permissions.remove(permission)
        # Remove only groups that confer this permission, retaining all other groups.
        target.groups.remove(*Group.objects.filter(permissions=permission))
    Activity.objects.create(
        user=target,
        actor=actor,
        action="moderator_access_changed",
        target_type="player",
        target_id=str(target.pk),
        changes={
            "enabled": enabled,
            "before": {"moderator": before},
            "after": {"moderator": enabled},
        },
    )


def ordinary_players():
    from django.db.models import Q

    return (
        User.objects.filter(is_staff=False, is_superuser=False)
        .exclude(
            Q(
                user_permissions__content_type__app_label="moderation",
                user_permissions__codename="access_workspace",
            )
            | Q(
                groups__permissions__content_type__app_label="moderation",
                groups__permissions__codename="access_workspace",
            )
        )
        .distinct()
    )


@transaction.atomic
def change_names(actor, user_id, data):
    from accounts.serializers import available_username
    from games.parties import refresh_account_name

    from .enforcement import schedule

    target = lock_player(user_id)
    authorize(actor, target)
    # Validate after locking, against the current account rather than a stale request.
    from .workspace_serializers import PlayerNamesInput

    serializer = PlayerNamesInput(data=data)
    serializer.is_valid(raise_exception=True)
    values = dict(serializer.validated_data)
    if "username" in values:
        try:
            values["username"] = available_username(values["username"], excluding=target.pk)
        except ValidationError as exc:
            raise ValidationError({"username": exc.detail}) from exc
    changes = {
        field: {"old": getattr(target, field), "new": value}
        for field, value in values.items()
        if value != getattr(target, field)
    }
    if not changes:
        return target
    for field, change in changes.items():
        setattr(target, field, change["new"])
    try:
        with transaction.atomic():
            # A staff correction leaves the player's self-service cooldown unchanged.
            target.save(update_fields=list(changes))
    except IntegrityError as exc:
        if "username" in changes:
            raise ValidationError({"username": ["This username is unavailable."]}) from exc
        raise
    Activity.objects.create(
        user=target, actor=actor, action="player_names_changed", changes=changes
    )
    refresh_account_name(target)
    schedule(target.pk)
    return target


@transaction.atomic
def submit_report(actor, subject, category, details):
    reporter = lock_player(actor.pk)
    restrictions = account_restrictions(reporter)
    if restrictions["blocked"]:
        raise PermissionDenied("Sign in with an account that can access this feature.")
    if restrictions["suspension"]:
        raise PermissionDenied("Reporting is unavailable while your account is suspended.")
    subject = get_object_or_404(User, pk=subject.pk)
    if reporter.pk == subject.pk:
        raise ValidationError({"subject": "You cannot report yourself."})
    from .models import Category

    if category not in Category.values or not details.strip() or len(details) > 2000:
        raise ValidationError("A valid category and written reason are required.")
    if Report.objects.filter(
        reporter=reporter,
        subject=subject,
        category=category,
        resolved_at__isnull=True,
        created_at__gte=timezone.now() - timedelta(days=1),
    ).exists():
        raise ValidationError(
            {
                "detail": "You already submitted this category of report for this player in the last day."
            }
        )
    report = Report.objects.create(
        reporter=reporter, subject=subject, category=category, details=details.strip()
    )
    Activity.objects.create(
        user=subject,
        actor=reporter,
        action="report_submitted",
        report=report,
        changes={"category": category},
    )
    return report
