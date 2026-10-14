from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import APIException

from accounts.models import User
from moderation.workspace import change_access


class Command(BaseCommand):
    help = "Grant/revoke native moderator access, with an administrator actor and audit record."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--actor", required=True, help="Existing administrator username")
        parser.add_argument("--revoke", action="store_true")

    def handle(self, *args, **options):
        try:
            target = User.objects.get(username__iexact=options["username"])
            actor = User.objects.get(
                username__iexact=options["actor"], is_superuser=True, is_active=True
            )
            change_access(actor, target.pk, not options["revoke"])
        except (User.DoesNotExist, APIException) as exc:
            raise CommandError(f"Unable to change moderator access: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Native moderator access {'revoked' if options['revoke'] else 'granted'} for @{target.username}. Django Admin access was not granted."
            )
        )
