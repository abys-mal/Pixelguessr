from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from library.models import ImageSubmission

pytestmark = pytest.mark.django_db


def test_submission_requires_account_and_is_pending(client, user, submission_data):
    assert (
        client.post("/api/library/submissions/", submission_data, format="json").status_code == 403
    )
    client.force_authenticate(user)
    response = client.post(
        "/api/library/submissions/",
        {**submission_data, "status": "approved", "submitted_by": "fake"},
        format="json",
    )
    assert response.status_code == 201
    image = ImageSubmission.objects.get()
    assert image.status == "pending" and image.submitted_by == user
    assert client.get("/api/library/catalog/").json()["count"] == 0


def test_approved_catalog_never_leaks_answers_or_references(client, user, staff, category):
    ImageSubmission.objects.create(
        submitted_by=user,
        category=category,
        canonical_answer="red panda",
        accepted_synonyms=["lesser panda"],
        source="commons",
        source_url="https://example.com/red-panda",
        external_image_url="https://example.com/red-panda.jpg",
        license="CC0",
        attribution="Photographer",
        status="approved",
        reviewed_by=staff,
        reviewed_at=timezone.now(),
    )
    response = client.get("/api/library/catalog/")
    assert response.status_code == 200
    assert set(response.json()["results"][0]) == {"id", "category", "created_at"}
    assert "panda" not in response.content.decode()
    assert "example.com" not in response.content.decode()


def test_user_cannot_read_other_submissions(client, user, staff, category):
    ImageSubmission.objects.create(
        submitted_by=staff,
        category=category,
        canonical_answer="secret",
        external_image_url="https://example.com/private.jpg",
        source="manual",
        license="Owned",
        attribution="Staff",
    )
    client.force_authenticate(user)
    assert client.get("/api/library/submissions/").json()["count"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"external_image_url": ""},
        {"external_image_url": "http://example.com/a.jpg"},
        {"external_image_url": "https://name:password@example.com/a.jpg"},
        {"accepted_synonyms": ["a"] * 31},
        {"accepted_synonyms": "string"},
        {"accepted_synonyms": [""]},
        {"source_url": ""},
    ],
)
def test_invalid_metadata_rejected(client, user, submission_data, changes):
    client.force_authenticate(user)
    assert (
        client.post(
            "/api/library/submissions/", {**submission_data, **changes}, format="json"
        ).status_code
        == 400
    )


def test_invalid_upload_rejected(client, user, submission_data, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client.force_authenticate(user)
    data = {
        **submission_data,
        "external_image_url": "",
        "accepted_synonyms": "[]",
        "image_file": SimpleUploadedFile("answer.png", b"not an image", content_type="image/png"),
    }
    assert client.post("/api/library/submissions/", data, format="multipart").status_code == 400


def test_upload_reencoded_private_and_staff_preview(
    client, user, staff, submission_data, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    buffer = BytesIO()
    Image.new("RGB", (128, 128), "red").save(buffer, format="PNG")
    client.force_authenticate(user)
    data = {
        **submission_data,
        "external_image_url": "",
        "accepted_synonyms": "[]",
        "image_file": SimpleUploadedFile(
            "red-panda-answer.png", buffer.getvalue(), content_type="image/png"
        ),
    }
    response = client.post("/api/library/submissions/", data, format="multipart")
    assert response.status_code == 201
    image = ImageSubmission.objects.get()
    assert "panda" not in image.image_file.name and image.image_file.name.endswith(".webp")
    assert "image_file" not in response.json()
    assert client.get(f"/api/library/submissions/{image.pk}/preview/").status_code == 403
    client.force_authenticate(staff)
    preview = client.get(f"/api/library/submissions/{image.pk}/preview/")
    assert preview.status_code == 200
    assert preview["Cache-Control"] == "private, no-store"
    try:
        client.force_authenticate(user=None)
        assert client.get(f"/api/library/submissions/{image.pk}/preview/").status_code == 403
        assert client.get(f"/media/{image.image_file.name}").status_code == 404
    finally:
        # Closing a streaming response sends request_finished and may close a real
        # database connection; finish all database assertions before cleanup.
        preview.close()
