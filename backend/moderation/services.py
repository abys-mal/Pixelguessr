from django.db.models import Q
from django.utils import timezone

from .models import Sanction


def active_sanctions(user):
    now = timezone.now()
    return user.sanctions.filter(starts_at__lte=now, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )


def account_restrictions(user):
    sanctions = list(active_sanctions(user))
    kinds = {s.kind for s in sanctions}
    return {
        "blocked": not user.is_active or Sanction.Kind.CLOSED in kinds,
        "suspension": Sanction.Kind.SUSPENSION in kinds,
        "probation": Sanction.Kind.PROBATION in kinds,
        "unacknowledged_warnings": [
            str(s.id)
            for s in sanctions
            if s.kind == Sanction.Kind.WARNING and not s.acknowledged_at
        ],
        "notice": sanction_notice(sanctions),
    }


def sanction_notice(sanctions):
    messages = {
        "suspension": "Your account is currently suspended from multiplayer activities. You can still play singleplayer and submit an appeal.",
        "probation": "Your account is on probation. Ranked duels and image submissions are temporarily unavailable.",
        "warning": "You have an unacknowledged warning. Please review it in your account settings.",
    }
    for kind in messages:
        notices = [
            s for s in sanctions if s.kind == kind and (kind != "warning" or not s.acknowledged_at)
        ]
        if notices:
            expiry = (
                max(s.expires_at for s in notices) if all(s.expires_at for s in notices) else None
            )
            return {
                "kind": kind,
                "message": messages[kind],
                "expires_at": expiry.isoformat() if expiry else None,
            }
    return None


def session_account(session):
    """Verify an existing normal session, including a now-closed identity, for denial messages only."""
    from django.conf import settings
    from django.utils.crypto import constant_time_compare

    from accounts.models import User

    if session.get("_auth_user_backend") not in settings.AUTHENTICATION_BACKENDS:
        return None
    user = User.objects.filter(pk=session.get("_auth_user_id")).first()
    if user and constant_time_compare(
        session.get("_auth_user_hash", ""), user.get_session_auth_hash()
    ):
        return user
    return None


def closed_session(request):
    user = request.user if request.user.is_authenticated else session_account(request.session)
    return bool(user and active_sanctions(user).filter(kind="closed").exists())
