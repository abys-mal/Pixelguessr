import uuid
from datetime import timedelta
from io import BytesIO, StringIO

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from games.models import Guess, GuestIdentity, Match, Participant, Round
from games.reveal import COVER_COLOR, prepare_image
from games.services import normalize_guess, revealed_count
from library.models import Category, ImageSubmission
from library.review import review_images
from library.serializers import SubmissionSerializer

pytestmark = pytest.mark.django_db
BASE = "/api/games/singleplayer/"


@pytest.fixture
def clock(monkeypatch):
    now = timezone.now()
    state = {"now": now}
    monkeypatch.setattr(timezone, "now", lambda: state["now"])
    return state


@pytest.fixture
def hosted(settings, tmp_path, user, staff, category):
    settings.MEDIA_ROOT = tmp_path
    data = BytesIO()
    Image.new("RGB", (960, 720), (220, 80, 45)).save(data, "PNG")
    serializer = SubmissionSerializer(
        data={
            "canonical_answer": "hot air balloon",
            "accepted_synonyms": ["balloon", "aerostat"],
            "category": category.pk,
            "source": "manual",
            "license": "CC0 1.0",
            "attribution": "Original test fixture",
            "image_file": SimpleUploadedFile("hot-air-balloon.png", data.getvalue(), "image/png"),
        }
    )
    serializer.is_valid(raise_exception=True)
    image = serializer.save(submitted_by=user)
    review_images(ImageSubmission.objects.filter(pk=image.pk), staff, "approved")
    image.refresh_from_db()
    return image


def start(client, request_id=None):
    return client.post(
        BASE + "rounds/", {"request_id": str(request_id or uuid.uuid4())}, format="json"
    )


def guess(client, round_id, text, request_id=None):
    return client.post(
        BASE + f"rounds/{round_id}/guesses/",
        {"guess": text, "request_id": str(request_id or uuid.uuid4())},
        format="json",
    )


def test_empty_and_pending_library(client, user, submission_data):
    assert client.get(BASE + "current/").json() == {"round": None}
    ImageSubmission.objects.create(
        submitted_by=user,
        **{**submission_data, "category": Category.objects.get(pk=submission_data["category"])},
    )
    response = start(client)
    assert response.status_code == 503 and response.json()["code"] == "library_empty"
    assert not Round.objects.exists() and not GuestIdentity.objects.exists()


def test_external_approved_references_are_not_fetched(client, user, staff, submission_data, clock):
    ImageSubmission.objects.create(
        submitted_by=user,
        **{**submission_data, "category": Category.objects.get(pk=submission_data["category"])},
        status="approved",
        reviewed_by=staff,
        reviewed_at=clock["now"],
    )
    assert start(client).json()["code"] == "library_empty"


def test_guest_csrf_ownership_and_refresh(hosted, clock):
    owner = APIClient(enforce_csrf_checks=True)
    assert start(owner).status_code == 403
    token = owner.get("/api/auth/csrf/").json()["csrfToken"]
    owner.credentials(HTTP_X_CSRFTOKEN=token)
    response = start(owner)
    assert response.status_code == 201
    data = response.json()["round"]
    assert data["revealed_count"] == 0 and data["grid_size"] == 20
    participant = Participant.objects.get()
    assert participant.user is None and participant.guest_id
    assert owner.get(BASE + "current/").json()["round"]["id"] == data["id"]
    reconnect = APIClient()
    reconnect.cookies = owner.cookies.copy()
    assert reconnect.get(BASE + "current/").json()["round"]["id"] == data["id"]
    stranger = APIClient()
    assert stranger.get(BASE + f"rounds/{data['id']}/").status_code == 404
    assert stranger.get(data["image_url"]).status_code == 404
    assert guess(stranger, data["id"], "balloon").status_code == 404
    assert guess(owner, data["id"], "nope").status_code == 200
    assert response["Cache-Control"] == "private, no-store"


def test_authenticated_round(client, hosted, user):
    client.force_authenticate(user)
    assert start(client).status_code == 201
    assert Participant.objects.get().user == user
    assert not GuestIdentity.objects.exists()


def test_private_answer_and_order_not_exposed(client, hosted, clock):
    data = start(client).json()["round"]
    response = client.get(BASE + f"rounds/{data['id']}/")
    text = response.content.decode()
    for secret in [
        hosted.canonical_answer,
        *hosted.accepted_synonyms,
        hosted.image_file.name,
        str(hosted.id),
        "synonyms",
        "storage",
        "seed",
        "reveal_order",
    ]:
        assert secret not in text
    assert data["revealed_tiles"] == [] and data["completion"] is None
    wrong = guess(client, data["id"], "wrong").json()
    assert wrong["round"]["completion"] is None
    assert "balloon" not in str(wrong)
    assert client.get("/media/" + hosted.image_file.name).status_code == 404


@pytest.mark.parametrize(
    "answer",
    ["  HOT   AIR BALLOON!! ", "hot-air-balloon", "Balloon.", "AEROSTAT", "ＨＯＴ AIR balloon"],
)
def test_canonical_synonyms_and_normalization(client, hosted, answer, clock):
    data = start(client).json()["round"]
    result = guess(client, data["id"], answer).json()
    assert result["result"] == "correct"
    assert result["round"]["status"] == "solved"
    assert result["round"]["completion"]["answer"] == "hot air balloon"
    assert "synonyms" not in str(result)
    assert result["round"]["revealed_count"] == 400
    assert Match.objects.get().status == "complete"
    again = guess(client, data["id"], answer).json()
    assert again["result"] == "already_solved" and Guess.objects.count() == 1


def test_unlimited_wrong_guesses_no_cooldown_and_validation(client, hosted):
    data = start(client).json()["round"]
    for count in range(1, 16):
        result = guess(client, data["id"], "wrong").json()
        assert result["result"] == "incorrect" and result["round"]["guess_count"] == count
    assert guess(client, data["id"], "!!!").status_code == 400
    assert guess(client, data["id"], "a" * 121).status_code == 400
    state = Round.objects.get().player_states.get()
    assert state.cooldown_until is None and state.score == 0
    assert normalize_guess("Bird’s") == "birds"


def test_idempotent_start_and_guess(client, hosted, clock):
    request_id = uuid.uuid4()
    data = start(client, request_id).json()["round"]
    assert start(client, request_id).json()["round"]["id"] == data["id"]
    assert Round.objects.count() == 1
    guess_id = uuid.uuid4()
    first = guess(client, data["id"], "wrong", guess_id).json()
    second = guess(client, data["id"], "wrong", guess_id).json()
    assert first == second and Guess.objects.count() == 1
    assert guess(client, data["id"], "different", guess_id).status_code == 409
    assert start(APIClient(), request_id).status_code == 404


def test_reveal_timing_and_no_early_pixels(client, hosted, clock):
    data = start(client).json()["round"]
    game_round = Round.objects.get()
    source = prepare_image(hosted.image_file.name)
    order = list(game_round.reveal_order)
    assert sorted(order) == list(range(400))
    for seconds, count in [(-1, 0), (0, 0), (15, 200), (29.999, 399), (30, 400), (35, 400)]:
        clock["now"] = game_round.reveal_started_at + timedelta(seconds=seconds)
        assert revealed_count(game_round, clock["now"]) == count
        # Arbitrary client versions cannot skip the authoritative reveal.
        image_response = client.get(data["image_url"] + "&v=400&elapsed=999999")
        assert (
            image_response.status_code == 200 and int(image_response["X-Revealed-Tiles"]) == count
        )
        assert image_response["Cache-Control"] == "private, no-store"
        rendered = Image.open(BytesIO(image_response.content)).convert("RGB")
        visible = set(order[:count])
        for tile in range(400):
            row, col = divmod(tile, 20)
            # Check interiors and boundaries: even tile edges contain no hidden pixels.
            for offset in [(0, 0), (23, 17), (47, 35)]:
                point = (col * 48 + offset[0], row * 36 + offset[1])
                assert rendered.getpixel(point) == (
                    source.getpixel(point) if tile in visible else COVER_COLOR
                )
        snapshot = client.get(BASE + "current/").json()["round"]
        assert snapshot["status"] == "active" and snapshot["completion"] is None
        assert snapshot["revealed_tiles"] == order[:count]
    cache.clear()
    assert client.get(BASE + "current/").json()["round"]["revealed_tiles"] == order
    assert guess(client, data["id"], "balloon").json()["result"] == "correct"


def test_expired_round_and_restart(client, hosted, clock):
    data = start(client).json()["round"]
    game_round = Round.objects.get()
    clock["now"] = game_round.expires_at + timedelta(seconds=1)
    result = guess(client, data["id"], "balloon")
    assert result.status_code == 410 and result.json()["round"]["status"] == "expired"
    assert Match.objects.get().status == "abandoned" and Guess.objects.count() == 0
    assert client.get(data["image_url"]).status_code == 410
    assert client.get(BASE + "current/").json()["round"]["image_url"] is None
    assert start(client).status_code == 201


def test_new_round_abandons_previous_and_snapshots_answers(client, hosted, clock, settings):
    settings.SINGLEPLAYER_GRID_SIZE = 10
    old = start(client).json()["round"]
    assert old["total_tiles"] == 100
    new = start(client).json()["round"]
    assert new["id"] != old["id"]
    assert client.get(BASE + f"rounds/{old['id']}/").json()["round"]["status"] == "expired"
    hosted.canonical_answer = "edited title"
    hosted.accepted_synonyms = []
    hosted.save()
    settings.SINGLEPLAYER_GRID_SIZE = 20
    assert guess(client, new["id"], "balloon").json()["round"]["total_tiles"] == 100


def test_missing_storage_image_is_clear_error(client, hosted):
    storage_name = hosted.image_file.name
    hosted.image_file.delete(save=False)
    response = start(client)
    assert response.status_code == 503 and response.json()["code"] == "image_unavailable"
    assert storage_name not in response.content.decode()
    assert not Round.objects.exists()


def test_development_import_explicit_review_only(settings, tmp_path, user, submission_data):
    if connection.vendor != "sqlite":
        pytest.skip("Development fixture command deliberately requires SQLite.")
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    pending = ImageSubmission.objects.create(
        submitted_by=user,
        **{**submission_data, "category": Category.objects.get(pk=submission_data["category"])},
    )
    output = StringIO()
    call_command("seed_dev_images", stdout=output)
    assert ImageSubmission.objects.filter(status="pending").count() == 5
    assert not ImageSubmission.objects.filter(status="approved").exists()
    curator = User.objects.get(username="pixelguessr-dev-curator")
    assert not curator.is_active and not curator.has_usable_password()
    call_command("seed_dev_images", approve=True, stdout=output)
    assert ImageSubmission.objects.filter(status="approved").count() == 4
    pending.refresh_from_db()
    assert pending.status == "pending" and pending.reviewed_by is None
    call_command("seed_dev_images", approve=True, stdout=output)
    assert ImageSubmission.objects.count() == 5
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_dev_images", stdout=output)


def test_review_change_during_start_is_rechecked(client, hosted, staff, monkeypatch):
    original = prepare_image

    def revoke_while_preparing(name):
        image = original(name)
        review_images(ImageSubmission.objects.filter(pk=hosted.pk), staff, "rejected")
        return image

    monkeypatch.setattr("games.reveal.prepare_image", revoke_while_preparing)
    response = start(client)
    assert response.status_code == 503 and response.json()["code"] == "image_unavailable"
    assert not Round.objects.exists() and not Match.objects.exists()
