import getpass
import warnings

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from accounts.lifecycle import invalidate_sessions
from accounts.models import User
from moderation.enforcement import schedule
from moderation.workspace import lock_player


class Command(BaseCommand):
    help = (
        "Reset a player's password using hidden interactive prompts; invalidate existing sessions."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    @sensitive_variables()
    def handle(self, *args, **options):
        user = User.objects.filter(username__iexact=options["username"]).first()
        if not user:
            raise CommandError("Account not found.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                password = getpass.getpass("New password: ")
                confirmation = getpass.getpass("Confirm new password: ")
            if password != confirmation:
                raise CommandError("Passwords do not match.")
            with transaction.atomic():
                user = lock_player(user.pk)
                validate_password(password, user)
                user.set_password(password)
                user.save(update_fields=["password"])
                invalidate_sessions(user.pk)
                schedule(user.pk)
        except ValidationError as exc:
            raise CommandError(
                "Password does not meet the configured validation requirements: "
                + "; ".join(exc.messages)
            ) from None
        except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
            raise CommandError(
                "Password reset cancelled; use a secure interactive terminal."
            ) from None
        self.stdout.write(
            self.style.SUCCESS("Password updated. Existing sessions have been invalidated.")
        )
