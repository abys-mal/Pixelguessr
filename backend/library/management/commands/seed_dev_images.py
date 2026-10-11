import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from library.dev_art import ATTRIBUTION, DEV_ART, illustration
from library.models import Category, ImageSubmission
from library.review import review_images
from library.serializers import SubmissionSerializer

NAMESPACE = uuid.UUID("b7d3d9ab-c67e-48af-bff3-6b92379aabf5")


class Command(BaseCommand):
    help = "Import four original CC0 development illustrations as PENDING. --approve explicitly reviews only those originals."

    def add_arguments(self, parser):
        parser.add_argument(
            "--approve",
            action="store_true",
            help="Explicitly approve only these generated original illustrations via the shared staff-review operation",
        )

    def handle(self, *args, **options):
        if (
            not settings.DEBUG
            or settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3"
        ):
            raise CommandError("This development-only command requires DEBUG=True and SQLite.")
        curator, created = User.objects.get_or_create(
            username="pixelguessr-dev-curator",
            defaults={
                "email": "dev-curator@pixelguessr.invalid",
                "display_name": "Development artwork curator",
                "is_staff": True,
                "is_active": False,
            },
        )
        if created:
            curator.set_unusable_password()
            curator.save(update_fields=["password"])
        if curator.is_active or not curator.is_staff or curator.has_usable_password():
            raise CommandError(
                "The development curator must remain disabled with an unusable password."
            )
        ids = []
        for answer, synonyms, slug in DEV_ART:
            image_id = uuid.uuid5(NAMESPACE, answer)
            image = ImageSubmission.objects.filter(pk=image_id).first()
            if image is None:
                data = {
                    "canonical_answer": answer,
                    "accepted_synonyms": synonyms,
                    "category": Category.objects.get(slug=slug).pk,
                    "source": "manual",
                    "license": "CC0 1.0",
                    "attribution": ATTRIBUTION,
                    "image_file": ContentFile(illustration(answer), name="original.png"),
                }
                serializer = SubmissionSerializer(data=data)
                serializer.is_valid(raise_exception=True)
                image = serializer.save(id=image_id, submitted_by=curator)
                self.stdout.write(f"Imported original development illustration: {answer} (pending)")
            if (
                image.submitted_by_id != curator.pk
                or image.attribution != ATTRIBUTION
                or image.canonical_answer != answer
                or image.accepted_synonyms != synonyms
            ):
                raise CommandError(
                    "An existing development record was edited. Review it manually; nothing will be overwritten."
                )
            ids.append(image.pk)
        if options["approve"]:
            originals = ImageSubmission.objects.filter(
                pk__in=ids, status=ImageSubmission.Status.PENDING
            )
            count = originals.count()
            review_images(originals, curator, ImageSubmission.Status.APPROVED)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Explicitly reviewed and approved {count} original development images. User submissions were not changed."
                )
            )
        else:
            self.stdout.write(
                "Images remain private and pending. Approve them in Admin, or explicitly run seed_dev_images --approve to review these known originals."
            )
