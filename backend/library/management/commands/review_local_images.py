from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from accounts.models import User
from library.local_import import (
    manifest_image,
    metadata,
    read_manifest,
    validate_approval,
    write_manifest,
)
from library.models import ImageSubmission
from library.review import review_images
from moderation.services import account_restrictions


class Command(BaseCommand):
    help = "Explicitly approve a verified local-import manifest through the existing staff-review operation. Requires a real active staff reviewer."

    def add_arguments(self, parser):
        parser.add_argument("manifest", type=Path)
        parser.add_argument("--reviewer", required=True, help="Existing active staff username")

    def handle(self, *args, **options):
        committed = False
        try:
            rows = read_manifest(options["manifest"])
            if not rows or any(not row["image_id"] or row["error"] for row in rows):
                raise ValueError(
                    "Every manifest row must be imported without errors before collection approval."
                )
            write_manifest(options["manifest"], rows)
            with transaction.atomic():
                ids = sorted({row["image_id"] for row in rows})
                ImageSubmission.objects.filter(pk__in=ids).update(status=F("status"))
                reviewer = User.objects.get(
                    username=options["reviewer"], is_staff=True, is_active=True
                )
                if account_restrictions(reviewer)["blocked"]:
                    raise ValueError("The reviewer account is closed.")
                for row in rows:
                    image = manifest_image(row)
                    if image.status == ImageSubmission.Status.REJECTED:
                        raise ValueError(
                            "Rejected images require separate review; collection approval will not overwrite them."
                        )
                    data, meta = metadata(row)
                    if any(
                        getattr(image, key + "_id" if key == "category" else key) != value
                        for key, value in data.items()
                    ) or any(
                        image.local_import_metadata.get(key) != meta[key]
                        for key in (
                            "description",
                            "difficulty",
                            "photographer",
                            "review_notes",
                            "label_verified",
                            "metadata_verified",
                        )
                    ):
                        raise ValueError(
                            "Manifest metadata differs from the database. Run import_local_images --update-metadata first."
                        )
                    validate_approval(image)
                pending = ImageSubmission.objects.filter(
                    pk__in=ids, status=ImageSubmission.Status.PENDING
                )
                count = pending.count()
                review_images(pending, reviewer, ImageSubmission.Status.APPROVED)
            committed = True
            for row in rows:
                row["import_status"] = "approved"
            write_manifest(options["manifest"], rows)
        except Exception as exc:
            if committed:
                raise CommandError(
                    f"Database review committed, but the manifest could not be updated: {exc}. Close the CSV editor and rerun review_local_images to reconcile it; already approved images will not be reviewed twice."
                ) from exc
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Explicitly approved {count} verified images. Originals were not needed."
            )
        )
