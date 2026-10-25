"""IP controls are independent of account sanctions and never grant permissions."""

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from core.client_ip import ClientIPError, normalize_ip, request_ip, scope_ip

ACTIVITIES = {
    "registration": "Account registration",
    "login": "Login",
    "singleplayer": "Singleplayer",
    "parties": "Parties",
    "submissions": "Image submissions",
    "community": "Community interactions",
}


class IPAccessDenied(PermissionDenied):
    def __init__(self, *, unidentified=False, login_restricted=False):
        self.login_restricted = login_restricted
        super().__init__(
            {
                "detail": "Unable to verify network access. Please contact support."
                if unidentified
                else "This activity is unavailable from your network.",
                "code": "client_ip_unavailable" if unidentified else "ip_restricted",
            }
        )


def restrictions_for_ip(address):
    from .models import IPAccessEntry

    address = normalize_ip(address)
    # Include list kind so the per-list unique index serves this hot-path lookup.
    entries = list(
        IPAccessEntry.objects.filter(address=address, list_kind__in=IPAccessEntry.ListKind.values)
    )
    if any(entry.list_kind == "whitelist" for entry in entries):
        return set()
    now = timezone.now()
    return {
        activity
        for entry in entries
        if entry.list_kind == "blacklist" and (entry.expires_at is None or entry.expires_at > now)
        for activity in entry.activities
    }


def staff_exempt(user):
    if not getattr(user, "is_authenticated", False):
        return False
    from accounts.models import User

    from .permissions import is_moderator

    # Socket users and permission caches can outlive a promotion/demotion.
    current = User.objects.filter(pk=user.pk).first()
    return current is not None and is_moderator(current)


def enforce_ip(address, activity=None, *, authenticated=False, user=None):
    try:
        restrictions = restrictions_for_ip(address)
    except ClientIPError as exc:
        raise IPAccessDenied(unidentified=True) from exc
    enforce_restrictions(restrictions, activity, authenticated=authenticated, user=user)


def enforce_restrictions(restrictions, activity, *, authenticated=False, user=None):
    login_blocked = "login" in restrictions and (authenticated or activity == "login")
    guest_blocked = not authenticated and activity in restrictions
    if login_blocked or guest_blocked:
        if not staff_exempt(user):
            raise IPAccessDenied(login_restricted=login_blocked)


def enforce_request(request, activity, *, authenticated=False, user=None):
    try:
        address = request_ip(request)
    except ClientIPError as exc:
        raise IPAccessDenied(unidentified=True) from exc
    try:
        enforce_ip(address, activity, authenticated=authenticated, user=user or request.user)
    except IPAccessDenied as exc:
        if (
            exc.login_restricted
            and request.user.is_authenticated
            and (user is None or not staff_exempt(request.user))
        ):
            from django.contrib.auth import logout

            logout(request)
        raise


def enforce_scope(scope, activity):
    try:
        address = scope_ip(scope)
    except ClientIPError as exc:
        raise IPAccessDenied(unidentified=True) from exc
    restrictions = restrictions_for_ip(address)
    if "login" not in restrictions and activity not in restrictions:
        return
    # A socket's cached identity must not turn a deleted session into a signed-in
    # exemption. Read the durable session only when a matching rule requires it.
    from importlib import import_module
    from types import SimpleNamespace

    from django.conf import settings
    from django.contrib.auth import get_user
    from django.contrib.auth.models import AnonymousUser

    session = scope["session"]
    fresh = import_module(settings.SESSION_ENGINE).SessionStore(session_key=session.session_key)
    user = get_user(SimpleNamespace(session=fresh))
    was_authenticated = bool(getattr(scope.get("user"), "is_authenticated", False))
    scope["user"] = user
    try:
        if "login" in restrictions and was_authenticated and not user.is_authenticated:
            raise IPAccessDenied(login_restricted=True)
        enforce_restrictions(restrictions, activity, authenticated=user.is_authenticated, user=user)
    except IPAccessDenied as exc:
        if exc.login_restricted:
            session.flush()
            scope["user"] = AnonymousUser()
        raise
