"""Account mutations use fresh password checks and durable per-user serialization."""

from datetime import timedelta

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import PermissionDenied, ValidationError

from moderation.services import account_restrictions

from .models import User
from .serializers import available_email, available_username


def username_available_at(user):
    return user.last_username_change + timedelta(days=90)


def settings_payload(user):
    available_at = username_available_at(user)
    return {
        "username": user.username,
        "email": user.email,
        "username_change_available": timezone.now() >= available_at,
        "username_change_available_at": available_at.isoformat(),
    }


@sensitive_variables()
def change_account(user_id, operation, data):
    with transaction.atomic():
        # UPDATE before mutable reads serializes requests on SQLite and PostgreSQL.
        # A SELECT FOR UPDATE alone would not serialize SQLite submissions.
        User.objects.filter(pk=user_id).update(last_username_change=F("last_username_change"))
        user = User.objects.get(pk=user_id)
        restrictions = account_restrictions(user)
        if restrictions["blocked"]:
            raise PermissionDenied("Resolve your account notice before updating your account.")
        if not user.check_password(data["current_password"]):
            raise ValidationError({"current_password": "Current password is incorrect."})
        if operation == "username":
            value = User.normalize_username(data["new_username"])
            if value.casefold() == user.username.casefold():
                raise ValidationError({"new_username": "Choose a different username."})
            now = timezone.now()
            available_at = username_available_at(user)
            if now < available_at:
                raise ValidationError(
                    {
                        "detail": f"You can change your username again on {available_at:%B %d, %Y} (UTC).",
                        "username_change_available_at": available_at.isoformat(),
                    }
                )
            try:
                user.username = available_username(value, excluding=user.pk)
            except ValidationError as exc:
                raise ValidationError({"new_username": exc.detail}) from exc
            user.last_username_change = now
            user.save(update_fields=["username", "last_username_change"])
        elif operation == "email":
            value = data["new_email"].lower()
            if value == user.email.lower():
                raise ValidationError({"new_email": "Choose a different email address."})
            try:
                user.email = available_email(value, excluding=user.pk)
            except ValidationError as exc:
                raise ValidationError({"new_email": exc.detail}) from exc
            user.save(update_fields=["email"])
        elif operation == "password":
            value = data["new_password"]
            if user.check_password(value):
                raise ValidationError({"new_password": "Choose a different password."})
            try:
                password_validation.validate_password(value, user)
            except DjangoValidationError as exc:
                raise ValidationError({"new_password": exc.messages}) from exc
            user.set_password(value)
            user.save(update_fields=["password"])
        else:
            raise ValueError("Unsupported account operation")
        return user
