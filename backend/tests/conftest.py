import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User
from library.models import Category


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="pixelplayer", email="player@example.com", password="a-strong-unique-pass-734"
    )


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        username="moderator",
        email="staff@example.com",
        password="a-strong-staff-pass-734",
        is_staff=True,
    )


@pytest.fixture
def category(db):
    return Category.objects.get(slug="nature")


@pytest.fixture
def submission_data(category):
    return {
        "canonical_answer": "red panda",
        "accepted_synonyms": ["lesser panda"],
        "category": category.pk,
        "source": "commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Red_panda.jpg",
        "external_image_url": "https://example.com/red-panda.jpg",
        "license": "CC BY-SA 4.0",
        "attribution": "Example photographer",
    }


@pytest.fixture(autouse=True)
def isolated_private_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "private-media"


@pytest.fixture
def uploaded_submission(submission_data):
    def make(**changes):
        import json
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        stream = BytesIO()
        Image.new("RGB", (100, 100), "blue").save(stream, format="PNG")
        values = {
            key: value for key, value in submission_data.items() if key != "external_image_url"
        }
        values["accepted_synonyms"] = json.dumps(values.get("accepted_synonyms", []))
        return {
            **values,
            "image_file": SimpleUploadedFile(
                "secret-answer.png", stream.getvalue(), content_type="image/png"
            ),
            "rights_acknowledged": "true",
            **changes,
        }

    return make
