import hashlib
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from library.local_import import (
    FIELDS,
    PROTOTYPE_LICENSE,
    import_image,
    manifest_image,
    read_manifest,
    record_result,
    update_metadata,
    write_manifest,
)


class Command(BaseCommand):
    help = "Import local JPG/JPEG photographs as private pending images using an editable CSV. Never approves or deletes originals."

    def add_arguments(self, parser):
        parser.add_argument("directory", nargs="?")
        parser.add_argument(
            "--manifest",
            type=Path,
            default=Path(settings.MEDIA_ROOT) / "imports" / "pexels-images.csv",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--verify-only",
            action="store_true",
            help="Decode/check manifest records without needing the Downloads folder",
        )
        mode.add_argument(
            "--update-metadata",
            action="store_true",
            help="Apply edited CSV metadata to pending records without needing originals",
        )

    def handle(self, *args, **options):
        manifest = options["manifest"].resolve()
        if manifest.suffix.lower() != ".csv":
            raise CommandError("The manifest must be a .csv file, never a source photograph.")
        try:
            rows = read_manifest(manifest)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        counts = Counter()
        if options["verify_only"] or options["update_metadata"]:
            if not rows:
                raise CommandError("A populated --manifest is required.")
            if options["verify_only"] and any(not row["image_id"] or row["error"] for row in rows):
                raise CommandError(
                    "The manifest still has incomplete or failed imports. Keep the original JPGs and resolve those rows before verification."
                )
            selected = [row for row in rows if row["image_id"]]
            if not selected:
                raise CommandError("The manifest has no imported image IDs.")
            for row in selected:
                try:
                    if options["update_metadata"]:
                        status, image = update_metadata(row)
                        row["import_status"] = status
                    else:
                        image = manifest_image(row)
                    record_result(row, image)
                    row["error"] = ""
                    counts["verified"] += 1
                except Exception as exc:
                    row["error"] = str(exc)
                    counts["failed"] += 1
                    self.stderr.write(f"{row['original_filename']}: {exc}")
            if options["update_metadata"]:
                write_manifest(manifest, rows)
        else:
            if not options["directory"]:
                raise CommandError(
                    "Provide a source directory, or use --verify-only/--update-metadata."
                )
            directory = Path(options["directory"]).resolve()
            if not directory.is_dir():
                raise CommandError(f"Source directory does not exist: {directory}")
            files = sorted(
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
            )
            counts["source_jpgs"] = len(files)
            if not files:
                raise CommandError("No JPG/JPEG photographs found; no records were changed.")
            by_name = {row["original_filename"]: row for row in rows}
            for path in files:
                name = path.relative_to(directory).as_posix()
                if name not in by_name:
                    row = dict.fromkeys(FIELDS, "")
                    row.update(
                        original_filename=name,
                        accepted_synonyms="[]",
                        label_verified="no",
                        metadata_verified="no",
                        license=PROTOTYPE_LICENSE if settings.PEXELS_PROTOTYPE_METADATA else "",
                    )
                    rows.append(row)
                    by_name[name] = row
            # Prove the manifest is writable before storing any files/records.
            write_manifest(manifest, rows)
            owner = None
            for path in files:
                row = by_name[path.relative_to(directory).as_posix()]
                try:
                    with path.open("rb") as file:
                        source_hash = hashlib.file_digest(file, "sha256").hexdigest()
                    if row["sha256"] and row["sha256"] != source_hash:
                        raise ValueError(
                            "Source JPEG changed since the manifest was prepared. Review it as a new input in a new manifest."
                        )
                    row["sha256"] = source_hash
                    row["error"] = ""
                    if not all(
                        row[field].strip()
                        for field in ("canonical_answer", "category", "difficulty")
                    ):
                        row["import_status"] = "needs_label"
                        counts["needs_label"] += 1
                        continue
                    if owner is None:
                        owner, _ = User.objects.get_or_create(
                            username="pixelguessr-local-importer",
                            defaults={
                                "email": "local-importer@pixelguessr.invalid",
                                "is_active": False,
                                "password": make_password(None),
                            },
                        )
                        if (
                            owner.is_active
                            or owner.is_staff
                            or owner.is_superuser
                            or owner.has_usable_password()
                        ):
                            raise ValueError(
                                "The local importer account must be inactive, unprivileged and have an unusable password."
                            )
                    status, image, converted = import_image(
                        row, path, owner, cleanup_error=self.stderr.write
                    )
                    counts["converted"] += 1
                    row["import_status"] = status
                    record_result(row, image)
                    counts[status] += 1
                    self.stdout.write(
                        f"{row['original_filename']}: {status} -> {image.image_file.name} ({converted.size[0]}x{converted.size[1]})"
                    )
                except Exception as exc:
                    row["import_status"] = "failed"
                    row["error"] = str(exc)
                    counts["failed"] += 1
                    self.stderr.write(f"{row['original_filename']}: {exc}")
                finally:
                    write_manifest(manifest, rows)
        unique = {row["image_id"]: row for row in rows if row["image_id"] and not row["error"]}
        total = 0
        for row in unique.values():
            try:
                total += record_result(row, manifest_image(row))
            except Exception as exc:
                counts["failed"] += 1
                self.stderr.write(f"Verification failed for {row['original_filename']}: {exc}")
        self.stdout.write(f"Manifest: {manifest}")
        self.stdout.write(
            f"Private storage: {settings.STORAGES['default']['BACKEND']} (local MEDIA_ROOT: {settings.MEDIA_ROOT})"
        )
        self.stdout.write(
            f"Results: {dict(counts)}; unique stored images: {len(unique)}; WebP bytes: {total}"
        )
        if counts["failed"]:
            raise CommandError(
                "Some images failed. Inspect per-image errors in the manifest; successful pending imports were retained."
            )
        if counts["needs_label"]:
            self.stdout.write(
                "Fill in answers, JSON synonym lists, category slugs and difficulty in the CSV, then rerun. Nothing is auto-approved."
            )
