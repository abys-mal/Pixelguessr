import json
import shutil
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from PIL import Image
from rest_framework.exceptions import ValidationError

from games.reveal import prepare_image
from games.services import approved_images, image_fields
from library.image_processing import convert_image
from library.local_import import FIELDS, read_manifest, verify_stored, write_manifest
from library.models import ImageSubmission
from library.review import review_images
from library.serializers import SubmissionSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def collection(tmp_path, settings):
    settings.PEXELS_PROTOTYPE_METADATA = False
    settings.MEDIA_ROOT = tmp_path / "private"
    source = tmp_path / "downloads"
    source.mkdir()
    return source, settings.MEDIA_ROOT / "imports" / "test.csv"


def jpeg(path, *, color="red", size=(160, 120), orientation=None):
    with Image.new("RGB", size, color) as image:
        exif = Image.Exif()
        exif[270] = "PRIVATE descriptive EXIF must not persist"
        if orientation:
            exif[274] = orientation
        image.save(path, format="JPEG", exif=exif)


def row(name="photo.jpg", **changes):
    value = dict.fromkeys(FIELDS, "")
    value.update(
        original_filename=name,
        canonical_answer="test photograph",
        accepted_synonyms=json.dumps(["test photo"]),
        category="nature",
        description="Synthetic photograph for automated testing",
        difficulty="easy",
        label_verified="yes",
        metadata_verified="no",
    )
    value.update(changes)
    return value


def run_import(collection, rows=None):
    source, manifest = collection
    if rows is not None:
        write_manifest(manifest, rows)
    output = StringIO()
    call_command(
        "import_local_images", str(source), manifest=manifest, stdout=output, stderr=StringIO()
    )
    return output.getvalue()


def allow_approval(manifest):
    rows = read_manifest(manifest)
    for entry in rows:
        entry.update(
            photographer="Synthetic test photographer",
            pexels_source_url="https://www.pexels.com/photo/test-only-fixture-123/",
            license="Test-only license declaration",
            metadata_verified="yes",
            label_verified="yes",
        )
    write_manifest(manifest, rows)
    call_command("import_local_images", manifest=manifest, update_metadata=True, stdout=StringIO())


def test_local_jpeg_orientation_downscale_metadata_and_no_upscale(tmp_path):
    path = tmp_path / "large.jpg"
    jpeg(path, size=(5000, 2000), orientation=6)
    with path.open("rb") as file:
        from django.core.files import File

        converted = convert_image(File(file), resize=True, jpeg_only=True)
    assert converted.original_size == (2000, 5000)
    assert converted.size[0] < converted.size[1] <= 4096
    assert converted.size[0] / converted.size[1] == pytest.approx(0.4, abs=0.001)
    with Image.open(converted.file) as decoded:
        assert decoded.format == "WEBP" and decoded.mode == "RGB"
        assert not decoded.getexif() and "exif" not in decoded.info
    jpeg(path, size=(160, 120))
    converted = convert_image(
        ContentFile(path.read_bytes(), name="small.jpg"), resize=True, jpeg_only=True
    )
    assert converted.size == (160, 120)


def test_http_upload_limits_are_not_relaxed_for_local_imports(tmp_path):
    path = tmp_path / "large.jpg"
    jpeg(path, size=(4200, 2000))
    with (
        patch(
            "PIL.JpegImagePlugin.JpegImageFile.load",
            side_effect=AssertionError("Oversized HTTP uploads must be rejected before decoding"),
        ),
        pytest.raises(ValidationError, match="dimensions"),
    ):
        SubmissionSerializer().validate_image_file(ContentFile(path.read_bytes(), name="large.jpg"))


@pytest.mark.parametrize("content", [b"not an image", b"", None])
def test_corrupt_or_non_jpeg_inputs_rejected(tmp_path, content):
    if content is None:
        output = BytesIO()
        Image.new("RGB", (100, 100)).save(output, format="PNG")
        content = output.getvalue()
    with pytest.raises(ValidationError):
        convert_image(ContentFile(content, name="pretend.jpg"), resize=True, jpeg_only=True)


def test_missing_labels_create_reviewable_manifest_without_guessing(collection):
    source, manifest = collection
    jpeg(source / "anything.JPEG")
    output = run_import(collection)
    entry = read_manifest(manifest)[0]
    assert entry["import_status"] == "needs_label" and entry["canonical_answer"] == ""
    assert len(entry["sha256"]) == 64 and "needs_label" in output
    assert not ImageSubmission.objects.exists()


def test_import_is_pending_private_and_independent_of_downloads(collection, client):
    source, manifest = collection
    path = source / "answer.jpg"
    jpeg(path)
    original = path.read_bytes()
    run_import(collection, [row("answer.jpg")])
    image = ImageSubmission.objects.get()
    assert image.status == "pending" and image.source == "manual"
    assert image.license == image.attribution == "UNVERIFIED"
    assert (
        image.local_import_metadata["description"] == "Synthetic photograph for automated testing"
    )
    assert "answer" not in image.image_file.name and image.image_file.name.endswith(".webp")
    assert path.read_bytes() == original
    assert client.get("/api/library/catalog/").json()["count"] == 0
    jpeg_path = path
    jpeg_path.unlink()  # Only this synthetic test fixture is removed.
    assert verify_stored(image)[1] == (160, 120)
    assert prepare_image(image.image_file.name).size == (960, 720)
    call_command("import_local_images", manifest=manifest, verify_only=True, stdout=StringIO())


def test_rerun_and_copied_files_are_idempotent(collection):
    source, manifest = collection
    jpeg(source / "one.jpg")
    shutil.copyfile(source / "one.jpg", source / "copy.jpeg")
    output = run_import(collection, [row("one.jpg"), row("copy.jpeg")])
    image = ImageSubmission.objects.get()
    assert "duplicate" in output
    files = list(Path(image.image_file.storage.location).glob("images/*.webp"))
    assert len(files) == 1
    first = (image.pk, image.image_file.name, image.local_import_metadata)
    run_import(collection)
    image.refresh_from_db()
    assert (image.pk, image.image_file.name, image.local_import_metadata) == first
    assert ImageSubmission.objects.count() == 1
    assert len({entry["content_sha256"] for entry in read_manifest(manifest)}) == 1


def test_manifest_edits_update_pending_metadata_without_new_files(collection):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    image = ImageSubmission.objects.get()
    original = (image.pk, image.image_file.name)
    rows = read_manifest(manifest)
    rows[0].update(
        canonical_answer="corrected answer",
        accepted_synonyms='["alternate"]',
        description="Corrected description",
        difficulty="medium",
    )
    write_manifest(manifest, rows)
    run_import(collection)
    image.refresh_from_db()
    assert (image.pk, image.image_file.name) == original
    assert image.canonical_answer == "corrected answer" and image.accepted_synonyms == ["alternate"]
    assert image.local_import_metadata["difficulty"] == "medium"
    source.rename(source.with_name("no-longer-downloads"))
    rows = read_manifest(manifest)
    rows[0]["canonical_answer"] = "offline correction"
    write_manifest(manifest, rows)
    call_command("import_local_images", manifest=manifest, update_metadata=True, stdout=StringIO())
    image.refresh_from_db()
    assert image.canonical_answer == "offline correction"


@pytest.mark.parametrize(
    "changes",
    [
        {"accepted_synonyms": '[""]'},
        {"category": "missing"},
        {"difficulty": "impossible"},
        {"pexels_source_url": "http://example.test/photo"},
        {"canonical_answer": "x" * 121},
        {"metadata_verified": "perhaps"},
    ],
)
def test_invalid_manifest_data_does_not_store_broken_records(collection, changes):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    with pytest.raises(CommandError):
        run_import(collection, [row(**changes)])
    assert not ImageSubmission.objects.exists()
    assert not list(manifest.parent.parent.glob("images/*.webp"))
    assert read_manifest(manifest)[0]["error"]


def test_per_image_errors_do_not_rollback_other_successful_imports(collection):
    source, manifest = collection
    jpeg(source / "good.jpg")
    (source / "corrupt.jpg").write_bytes(b"broken")
    with pytest.raises(CommandError):
        run_import(collection, [row("good.jpg"), row("corrupt.jpg")])
    assert ImageSubmission.objects.count() == 1
    entries = {entry["original_filename"]: entry for entry in read_manifest(manifest)}
    assert entries["good.jpg"]["import_status"] == "imported_pending"
    assert entries["corrupt.jpg"]["import_status"] == "failed"


@pytest.mark.parametrize("failure", ["storage", "database"])
def test_failed_registration_cleans_new_private_files(collection, failure):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    storage = ImageSubmission._meta.get_field("image_file").storage
    if failure == "storage":
        save = storage.save

        def fail_after_write(*args, **kwargs):
            save(*args, **kwargs)
            raise OSError("Simulated storage failure after writing")

        context = patch.object(storage, "save", side_effect=fail_after_write)
    else:
        context = patch.object(
            ImageSubmission, "save", side_effect=RuntimeError("Simulated database failure")
        )
    with context, pytest.raises(CommandError):
        run_import(collection, [row()])
    assert not ImageSubmission.objects.exists()
    assert not list(manifest.parent.parent.glob("images/*.webp"))


def test_unverified_approval_is_blocked_even_through_shared_review(collection, staff):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    image = ImageSubmission.objects.get()
    with pytest.raises(Exception, match="verified labels"):
        review_images(ImageSubmission.objects.all(), staff, "approved")
    image.refresh_from_db()
    assert image.status == "pending"
    with pytest.raises(CommandError):
        call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())


def test_explicit_approval_reuses_review_and_game_library_without_originals(collection, staff):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    (source / "photo.jpg").unlink()
    allow_approval(manifest)
    call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())
    image = ImageSubmission.objects.get()
    assert image.status == "approved" and image.reviewed_by_id == staff.pk and image.reviewed_at
    assert [entry.pk for entry in approved_images()] == [image.pk]
    from games import parties, ranked

    assert parties.approved_images is ranked.approved_images is approved_images
    assert image_fields(image)["image_storage_name"] == image.image_file.name
    assert prepare_image(image.image_file.name).size == (960, 720)
    call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())
    image.refresh_from_db()
    rows = read_manifest(manifest)
    rows[0]["canonical_answer"] = "do not overwrite"
    write_manifest(manifest, rows)
    call_command("import_local_images", manifest=manifest, update_metadata=True, stdout=StringIO())
    image.refresh_from_db()
    assert image.canonical_answer == "test photograph" and image.status == "approved"


def test_nonstaff_cannot_approve_imported_collection(collection, user):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    allow_approval(manifest)
    with pytest.raises(CommandError):
        call_command("review_local_images", manifest, reviewer=user.username, stdout=StringIO())
    assert ImageSubmission.objects.get().status == "pending"


def test_edited_source_or_missing_storage_is_reported_without_overwrite(collection):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    image = ImageSubmission.objects.get()
    stored = image.image_file.name
    jpeg(source / "photo.jpg", color="blue")
    with pytest.raises(CommandError):
        run_import(collection)
    assert ImageSubmission.objects.count() == 1 and image.image_file.storage.exists(stored)
    image.image_file.storage.delete(stored)
    with pytest.raises(CommandError):
        call_command(
            "import_local_images",
            manifest=manifest,
            verify_only=True,
            stdout=StringIO(),
            stderr=StringIO(),
        )


def test_manifest_atomic_replace_retries_windows_file_locks(collection):
    _, manifest = collection
    import os

    replace = os.replace
    calls = []

    def temporarily_locked(source, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError("Transient scanner lock")
        return replace(source, target)

    with (
        patch("library.local_import.os.replace", side_effect=temporarily_locked),
        patch("library.local_import.time.sleep"),
    ):
        write_manifest(manifest, [row()])
    assert len(calls) == 3 and read_manifest(manifest)[0]["canonical_answer"] == "test photograph"


def test_verify_does_not_claim_incomplete_collection_is_safe_to_remove(collection):
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection)
    with pytest.raises(CommandError, match="Keep the original JPGs"):
        call_command("import_local_images", manifest=manifest, verify_only=True, stdout=StringIO())


@pytest.mark.parametrize(
    "photographer,url",
    [
        ("", ""),
        ("Optional photographer", ""),
        ("", "https://www.pexels.com/photo/test-only-fixture-123/"),
        ("Optional photographer", "https://www.pexels.com/photo/test-only-fixture-123/"),
    ],
)
def test_prototype_defaults_and_approval_allow_optional_individual_metadata(
    collection, settings, staff, photographer, url
):
    settings.PEXELS_PROTOTYPE_METADATA = True
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(
        collection,
        [row(photographer=photographer, pexels_source_url=url, license="", metadata_verified="no")],
    )
    image = ImageSubmission.objects.get()
    original = (image.pk, image.image_file.name, image.local_import_digest)
    assert image.status == "pending"
    assert image.attribution == "Pexels" and image.license == "Pexels License"
    assert image.source_url == url
    assert image.local_import_metadata["photographer"] == photographer
    assert image.local_import_metadata["metadata_verified"] is False
    assert image.local_import_metadata["prototype_metadata"] is True
    call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())
    image.refresh_from_db()
    assert image.status == "approved" and image.reviewed_by_id == staff.pk
    assert image.pk in {entry.pk for entry in approved_images()}
    assert (image.pk, image.image_file.name, image.local_import_digest) == original
    run_import(collection)
    assert ImageSubmission.objects.count() == 1


def test_prototype_still_requires_label_review(collection, settings, staff):
    settings.PEXELS_PROTOTYPE_METADATA = True
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row(label_verified="no")])
    with pytest.raises(ModelValidationError, match="verified labels"):
        review_images(ImageSubmission.objects.all(), staff, "approved")
    with pytest.raises(CommandError, match="verified labels"):
        call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())
    assert ImageSubmission.objects.get().status == "pending"


def test_optional_source_metadata_can_be_added_before_approval(collection, settings, staff):
    settings.PEXELS_PROTOTYPE_METADATA = True
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    allow_approval(manifest)
    image = ImageSubmission.objects.get()
    assert image.attribution == "Pexels" and image.license == "Pexels License"
    assert image.local_import_metadata["photographer"] == "Synthetic test photographer"
    assert image.source_url == "https://www.pexels.com/photo/test-only-fixture-123/"
    call_command("review_local_images", manifest, reviewer=staff.username, stdout=StringIO())
    assert ImageSubmission.objects.get().status == "approved"


def test_disabling_prototype_restores_individual_provenance_requirement(
    collection, settings, staff
):
    settings.PEXELS_PROTOTYPE_METADATA = True
    source, manifest = collection
    jpeg(source / "photo.jpg")
    run_import(collection, [row()])
    settings.PEXELS_PROTOTYPE_METADATA = False
    with pytest.raises(ModelValidationError, match="photographer"):
        review_images(ImageSubmission.objects.all(), staff, "approved")


def test_prototype_setting_cannot_be_enabled_in_production(monkeypatch):
    import runpy

    from django.core.exceptions import ImproperlyConfigured

    for key, value in {
        "DEBUG": "False",
        "USE_SQLITE": "False",
        "LOCAL_SERVICES": "False",
        "DJANGO_SECRET_KEY": "test-only-config-key-" * 4,
        "DATABASE_URL": "postgresql://test:test@localhost/test",
        "REDIS_URL": "redis://localhost:6379/0",
        "PEXELS_PROTOTYPE_METADATA": "True",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ImproperlyConfigured, match="requires DEBUG=True"):
        runpy.run_path(str(Path(__file__).parents[1] / "config/settings.py"))
