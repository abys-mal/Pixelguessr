from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from core.client_ip import ClientIPError, normalize_ip
from moderation.ip_management import IPInput, save_entry
from moderation.models import IPAccessEntry


class Command(BaseCommand):
    help = "Server-local, audited recovery: whitelist one exact IP using an existing administrator."

    def add_arguments(self, parser):
        parser.add_argument("address")
        parser.add_argument("--administrator", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        try:
            address = normalize_ip(options["address"])
            actor = User.objects.get(username=options["administrator"])
            serializer = IPInput(data={"address": address, "reason": options["reason"]})
            serializer.is_valid(raise_exception=True)
            entry = IPAccessEntry.objects.filter(list_kind="whitelist", address=address).first()
            save_entry(
                actor, "whitelist", serializer.validated_data, pk=entry.pk if entry else None
            )
        except (ClientIPError, User.DoesNotExist) as exc:
            raise CommandError(
                "Choose a valid exact IP and an existing authorized administrator."
            ) from exc
        except Exception as exc:
            from rest_framework.exceptions import APIException

            if isinstance(exc, APIException):
                raise CommandError(str(exc.detail)) from exc
            raise
        self.stdout.write(
            "Recovery whitelist saved. Account sanctions and normal authentication still apply."
        )
