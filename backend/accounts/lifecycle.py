"""Password-verified voluntary closure; sessions are invalidated after durable state changes."""

from django.contrib.sessions.models import Session
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import PermissionDenied, ValidationError

from moderation.models import Sanction
from moderation.services import active_sanctions
from moderation.workspace import lock_player


def invalidate_sessions(user_id):
    keys = [
        session.session_key
        for session in Session.objects.all().iterator(chunk_size=200)
        if session.get_decoded().get("_auth_user_id") == str(user_id)
    ]
    Session.objects.filter(session_key__in=keys).delete()
    return len(keys)


@sensitive_variables()
def verify_password(user_id, current_password):
    from .models import User

    user = User.objects.get(pk=user_id)
    if not user.check_password(current_password):
        raise ValidationError({"current_password": "Current password is incorrect."})
    return user


@transaction.atomic
@sensitive_variables()
def close_account(user_id, current_password, confirmation):
    user = lock_player(user_id)
    if confirmation != "CLOSE MY ACCOUNT":
        raise ValidationError({"confirmation": "Type CLOSE MY ACCOUNT exactly."})
    verify_password(user.pk, current_password)
    if not user.is_active:
        raise PermissionDenied("This account is inactive.")
    closed = active_sanctions(user).filter(kind="closed").first()
    if closed:
        if closed.origin != "voluntary":
            raise PermissionDenied("This account is already closed.")
        return closed
    closure = Sanction.objects.create(
        user=user,
        issued_by=user,
        kind="closed",
        origin="voluntary",
        category="other",
        reason="Account voluntarily closed by its owner.",
    )
    invalidate_sessions(user.pk)
    return closure
