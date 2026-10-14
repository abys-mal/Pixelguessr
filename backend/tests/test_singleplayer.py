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
from games.services import normalize_guess, revealed_count, score_for_reveal
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
    assert client.get(BASE + "current/").json() == {"round": None, "session": None}
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
    assert Match.objects.get().status == "active"
    again = guess(client, data["id"], answer).json()
    assert again["result"] == "already_completed" and Guess.objects.count() == 1


def test_unlimited_wrong_guesses_no_cooldown_and_validation(client, hosted):
    data = start(client).json()["round"]
    for count in range(1, 16):
        result = guess(client, data["id"], "wrong").json()
        assert result["result"] == "incorrect" and result["round"]["guess_count"] == count
    assert guess(client, data["id"], "!!!").status_code == 400
    assert guess(client, data["id"], "a" * 121).status_code == 400
    state = Round.objects.get(number=1).player_states.get()
    assert state.cooldown_until is None and state.score == 0
    assert normalize_guess("Bird’s") == "birds"


def test_idempotent_start_and_guess(client, hosted, clock):
    request_id = uuid.uuid4()
    data = start(client, request_id).json()["round"]
    assert start(client, request_id).json()["round"]["id"] == data["id"]
    assert Round.objects.count() == 5
    guess_id = uuid.uuid4()
    first = guess(client, data["id"], "wrong", guess_id).json()
    second = guess(client, data["id"], "wrong", guess_id).json()
    assert first == second and Guess.objects.count() == 1
    assert guess(client, data["id"], "different", guess_id).status_code == 409
    assert start(APIClient(), request_id).status_code == 404


def test_reveal_timing_and_no_early_pixels(client, hosted, clock):
    data = start(client).json()["round"]
    game_round = Round.objects.get(number=1)
    source = prepare_image(hosted.image_file.name)
    order = list(game_round.reveal_order)
    assert sorted(order) == list(range(400))
    for seconds, count in [(-1, 0), (0, 0), (22.5, 200), (44.999, 399), (45, 400), (50, 400)]:
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
    game_round = Round.objects.get(number=1)
    clock["now"] = game_round.expires_at + timedelta(seconds=1)
    result = guess(client, data["id"], "balloon")
    assert result.status_code == 410 and result.json()["round"]["status"] == "expired"
    assert Match.objects.get().status == "abandoned" and Guess.objects.count() == 0
    assert client.get(data["image_url"]).status_code == 410
    assert client.get(BASE + "current/").json()["round"]["image_url"] is None
    assert start(client).status_code == 201


def test_no_restart_skip_and_snapshots_answers(client, hosted, clock, settings):
    settings.SINGLEPLAYER_GRID_SIZE = 10
    old = start(client).json()["round"]
    assert old["total_tiles"] == 100
    assert start(client).status_code == 409
    assert next_round(client, old["id"]).status_code == 409
    hosted.canonical_answer = "edited title"
    hosted.accepted_synonyms = []
    hosted.save()
    settings.SINGLEPLAYER_GRID_SIZE = 20
    assert guess(client, old["id"], "balloon").json()["round"]["total_tiles"] == 100
    new = next_round(client, old["id"]).json()["round"]
    # New rounds take their reviewed answer at activation; round configuration is snapshotted.
    assert new["total_tiles"] == 100
    assert guess(client, new["id"], "edited title").json()["result"] == "correct"


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


def next_round(client, round_id, request_id=None):
    return client.post(
        BASE + f"rounds/{round_id}/next/",
        {"request_id": str(request_id or uuid.uuid4())},
        format="json",
    )


def forfeit(client, round_id):
    return client.post(BASE + f"rounds/{round_id}/forfeit/", {}, format="json")


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, 1000),
        (40, 810),
        (100, 563),
        (200, 250),
        (300, 63),
        (400, 0),
        (-1, 1000),
        (401, 0),
        (1, 995),
        (399, 0),
    ],
)
def test_score_formula_and_half_up_boundaries(count, expected):
    assert score_for_reveal(count, 400) == expected
    assert 0 <= score_for_reveal(count, 400) <= 1000


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, 1000), (4.5, 810), (11.25, 563), (22.5, 250), (33.75, 63), (45, 0), (60, 0)],
)
def test_authoritative_correct_score(client, hosted, clock, seconds, expected):
    data = start(client).json()
    game_round = Round.objects.get(pk=data["round"]["id"])
    assert game_round.reveal_duration_seconds == 45
    clock["now"] = game_round.reveal_started_at + timedelta(seconds=seconds)
    wrong = guess(client, str(game_round.pk), "incorrect").json()
    assert wrong["round"]["score"] == 0 and wrong["session"]["total_score"] == 0
    result = guess(client, str(game_round.pk), "balloon").json()
    assert result["round"]["score"] == expected
    assert result["round"]["completion"]["score"] == expected
    assert result["session"]["total_score"] == expected
    assert game_round.player_states.get().score == expected
    assert Participant.objects.get().total_score == expected
    # Completion is immutable even when a later submission claims a different time/score.
    replay = guess(client, str(game_round.pk), "balloon").json()
    assert replay["session"]["total_score"] == expected
    assert Guess.objects.filter(round=game_round).count() == 2


def test_five_rounds_max_score_and_play_again(client, hosted, clock):
    first_id = uuid.uuid4()
    data = start(client, first_id).json()
    original_match = Match.objects.get()
    assert original_match.rounds.count() == 5
    assert sum(item.reveal_started_at is not None for item in original_match.rounds.all()) == 1
    assert data["session"]["max_score"] == 5000 and data["session"]["total_score"] == 0
    for number in range(1, 6):
        round_id = data["round"]["id"]
        assert data["round"]["number"] == number
        data = guess(client, round_id, "balloon").json()
        assert data["round"]["score"] == 1000 and data["session"]["total_score"] == number * 1000
        assert data["session"]["status"] == ("complete" if number == 5 else "active")
        if number < 5:
            request_id = uuid.uuid4()
            data = next_round(client, round_id, request_id).json()
            replay = next_round(client, round_id, request_id).json()
            assert replay["round"]["id"] == data["round"]["id"]
            assert replay["session"]["revision"] == data["session"]["revision"]
            assert replay["round"]["number"] == number + 1
    assert data["session"]["solved_rounds"] == 5
    assert [item["score"] for item in data["session"]["rounds"]] == [1000] * 5
    assert next_round(client, data["round"]["id"]).json()["result"] == "session_complete"
    assert original_match.rounds.count() == 5
    assert start(client, first_id).json()["session"]["total_score"] == 5000
    fresh = start(client).json()
    assert fresh["session"]["id"] != data["session"]["id"] and fresh["session"]["total_score"] == 0
    assert fresh["round"]["number"] == 1 and Round.objects.count() == 10
    original_match.refresh_from_db()
    assert (
        original_match.status == "complete"
        and original_match.participants.get().total_score == 5000
    )


def test_forfeit_before_full_reveal_denied_and_repeated_is_safe(client, hosted, clock):
    data = start(client).json()
    game_round = Round.objects.get(pk=data["round"]["id"])
    assert forfeit(client, str(game_round.pk)).status_code == 409
    clock["now"] = game_round.reveal_started_at + timedelta(seconds=44.999)
    assert forfeit(client, str(game_round.pk)).status_code == 409
    clock["now"] = game_round.reveal_started_at + timedelta(seconds=45)
    result = forfeit(client, str(game_round.pk)).json()
    assert result["result"] == "forfeited" and result["round"]["status"] == "forfeited"
    assert result["round"]["completion"]["answer"] == "hot air balloon"
    assert result["round"]["score"] == result["session"]["total_score"] == 0
    assert forfeit(client, str(game_round.pk)).json()["result"] == "already_completed"
    assert guess(client, str(game_round.pk), "balloon").json()["result"] == "already_completed"
    assert not Guess.objects.exists() and game_round.player_states.get().solved_at is None
    game_round.refresh_from_db()
    assert game_round.winner is None and game_round.outcome == "forfeited"


def test_five_forfeits_final_results(client, hosted, clock):
    data = start(client).json()
    for number in range(1, 6):
        current = Round.objects.get(pk=data["round"]["id"])
        clock["now"] = current.reveal_started_at + timedelta(seconds=45)
        data = forfeit(client, str(current.pk)).json()
        assert data["session"]["total_score"] == 0 and data["round"]["number"] == number
        if number < 5:
            data = next_round(client, str(current.pk)).json()
    assert data["session"]["status"] == "complete" and data["session"]["solved_rounds"] == 0
    assert all(item["outcome"] == "forfeited" for item in data["session"]["rounds"])


def test_pending_rounds_are_private_and_cannot_be_skipped(client, hosted):
    data = start(client).json()
    future = Round.objects.get(number=2)
    assert future.reveal_started_at is None
    assert guess(client, str(future.pk), "balloon").status_code == 409
    assert forfeit(client, str(future.pk)).status_code == 409
    assert next_round(client, str(future.pk)).status_code == 409
    assert client.get(BASE + f"rounds/{future.pk}/image/?v=400").status_code == 409
    snapshot = client.get(BASE + f"rounds/{future.pk}/").json()["round"]
    assert snapshot["image_url"] is None and snapshot["completion"] is None
    assert snapshot["status"] == "pending" and snapshot["revealed_tiles"] == []
    assert "balloon" not in str(data["session"])
    assert not Guess.objects.exists()


def test_forfeit_and_next_require_csrf_and_ownership(hosted):
    owner = APIClient(enforce_csrf_checks=True)
    token = owner.get("/api/auth/csrf/").json()["csrfToken"]
    owner.credentials(HTTP_X_CSRFTOKEN=token)
    data = start(owner).json()
    rid = data["round"]["id"]
    stranger = APIClient()
    assert forfeit(stranger, rid).status_code == 404
    assert next_round(stranger, rid).status_code == 404
    owner.credentials()
    assert forfeit(owner, rid).status_code == 403
    assert next_round(owner, rid).status_code == 403


@pytest.mark.parametrize("library_size", [1, 2, 4, 5, 6])
def test_image_selection_unique_when_possible(client, hosted, staff, library_size, clock):
    for number in range(1, library_size):
        ImageSubmission.objects.create(
            submitted_by=hosted.submitted_by,
            category=hosted.category,
            canonical_answer=f"image {number}",
            accepted_synonyms=[],
            source="manual",
            image_file=hosted.image_file.name,
            license="CC0",
            attribution="Fixture",
            status="approved",
            reviewed_by=staff,
            reviewed_at=clock["now"],
        )
    data = start(client).json()
    selected = list(Round.objects.order_by("number").values_list("image_id", flat=True))
    assert len(set(selected)) == min(library_size, 5)
    if library_size > 1:
        assert all(a != b for a, b in zip(selected, selected[1:], strict=False))
    played = []
    for number in range(1, 6):
        current = Round.objects.get(pk=data["round"]["id"])
        played.append(current.image_id)
        data = guess(client, str(current.pk), current.answer_snapshot).json()
        if number < 5:
            data = next_round(client, str(current.pk)).json()
    assert len(set(played)) == min(library_size, 5)
    if library_size > 1:
        assert all(a != b for a, b in zip(played, played[1:], strict=False))


def test_guest_refresh_score_and_latest_round_recovery(client, hosted, clock):
    data = start(client).json()
    rid = data["round"]["id"]
    guess(client, rid, "balloon")
    data = next_round(client, rid).json()
    reconnect = APIClient()
    reconnect.cookies = client.cookies.copy()
    cache.clear()
    recovered = reconnect.get(BASE + "current/").json()
    assert recovered["round"]["id"] == data["round"]["id"]
    assert recovered["session"]["total_score"] == 1000
    assert recovered["session"]["revision"] == data["session"]["revision"]
    assert recovered["round"]["number"] == 2
    assert next_round(client, rid).json()["round"]["id"] == data["round"]["id"]
    assert forfeit(client, rid).json()["session"]["total_score"] == 1000


def test_authenticated_game_recovers_without_round_pointer(client, hosted, user):
    client.force_authenticate(user)
    data = start(client).json()
    other = APIClient()
    other.force_authenticate(user)
    recovered = other.get(BASE + "current/").json()
    assert recovered["session"]["id"] == data["session"]["id"]
    assert start(other).status_code == 409


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("operation", ["guess", "guess_forfeit", "next", "start"])
def test_concurrent_requests_are_serialized(client, hosted, user, clock, operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
        pytest.skip("Run with TEST_SQLITE_FILE to test real SQLite writer locks.")
    client.force_authenticate(user)
    data = start(client).json()
    rid = data["round"]["id"]
    if operation == "next":
        guess(client, rid, "balloon")
    if operation == "guess_forfeit":
        clock["now"] = Round.objects.get(pk=rid).reveal_started_at + timedelta(seconds=45)
    shared_id = uuid.uuid4()
    barrier = Barrier(2)

    def run(index):
        close_old_connections()
        worker = APIClient()
        worker.force_authenticate(user)
        try:
            barrier.wait(timeout=10)
            if operation == "next":
                response = next_round(worker, rid, shared_id)
            elif operation == "start":
                response = start(worker, data_request_id)
            elif operation == "guess_forfeit" and index == 1:
                response = forfeit(worker, rid)
            else:
                response = guess(worker, rid, "balloon", shared_id)
            return response.status_code, response.json()
        finally:
            close_old_connections()

    data_request_id = Round.objects.get(pk=rid).start_request_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert all(status in {200, 201} for status, _ in results)
    assert Match.objects.count() == 1 and Round.objects.count() == 5
    participant = Participant.objects.get()
    if operation == "next":
        assert len({body["round"]["id"] for _, body in results}) == 1
        assert Round.objects.filter(reveal_started_at__isnull=False).count() == 2
        assert participant.total_score == 1000
    elif operation == "guess":
        assert Guess.objects.count() == 1 and participant.total_score == 1000
        assert Round.objects.get(pk=rid).outcome == "solved"
    elif operation == "guess_forfeit":
        assert participant.total_score == 0 and Guess.objects.count() <= 1
        assert Round.objects.get(pk=rid).outcome in {"solved", "forfeited"}
    else:
        assert participant.total_score == 0 and Guess.objects.count() == 0


def test_client_score_and_time_claims_are_ignored(client, hosted, clock):
    data = start(client).json()
    game_round = Round.objects.get(pk=data["round"]["id"])
    clock["now"] = game_round.reveal_started_at + timedelta(seconds=22.5)
    response = client.post(
        BASE + f"rounds/{game_round.pk}/guesses/",
        {
            "request_id": str(uuid.uuid4()),
            "guess": "balloon",
            "score": 999999,
            "revealed_count": 0,
            "elapsed_seconds": 0,
            "r": 0,
        },
        format="json",
    )
    assert response.json()["round"]["score"] == 250
    assert response.json()["session"]["total_score"] == 250


def test_old_game_retry_cannot_hide_new_active_game(client, hosted, clock):
    request_id = uuid.uuid4()
    data = start(client, request_id).json()
    for number in range(1, 6):
        rid = data["round"]["id"]
        data = guess(client, rid, "balloon").json()
        if number < 5:
            data = next_round(client, rid).json()
    old_session = data["session"]["id"]
    fresh = start(client).json()
    assert start(client, request_id).json()["session"]["id"] == old_session
    recovered = client.get(BASE + "current/").json()
    assert recovered["session"]["id"] == fresh["session"]["id"]
    assert recovered["session"]["total_score"] == 0 and recovered["round"]["number"] == 1


def test_expiry_keeps_previously_earned_score(client, hosted, clock):
    data = start(client).json()
    guess(client, data["round"]["id"], "balloon")
    data = next_round(client, data["round"]["id"]).json()
    clock["now"] = Match.objects.get().singleplayer_expires_at + timedelta(seconds=1)
    expired = client.get(BASE + "current/").json()
    assert expired["session"]["status"] == "expired"
    assert expired["session"]["total_score"] == 1000
    assert expired["session"]["rounds"][0]["score"] == 1000
    assert "answer" not in expired["session"]["rounds"][1]
    assert forfeit(client, data["round"]["id"]).status_code == 410


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("same_request", [True, False])
def test_concurrent_new_starts_create_only_one_game(hosted, user, same_request):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    if connection.vendor == "sqlite" and "mode=memory" in str(connection.settings_dict["NAME"]):
        pytest.skip("Run with TEST_SQLITE_FILE to test real SQLite writer locks.")
    barrier = Barrier(2)
    request_ids = [uuid.uuid4(), uuid.uuid4()]
    if same_request:
        request_ids[1] = request_ids[0]

    def run(index):
        close_old_connections()
        worker = APIClient()
        worker.force_authenticate(user)
        try:
            barrier.wait(timeout=10)
            response = start(worker, request_ids[index])
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(run, [0, 1]))
    assert sorted(statuses) == ([201, 201] if same_request else [201, 409])
    assert Match.objects.count() == 1 and Round.objects.count() == 5
    assert Participant.objects.get().total_score == 0


def test_registered_start_uses_cookie_session_identity(hosted, client, user):
    client.force_login(user, backend="accounts.backends.AccountBackend")
    request_id = uuid.uuid4()
    response = start(client, request_id)
    assert response.status_code == 201
    game_round = Round.objects.get(pk=response.json()["round"]["id"])
    participant = game_round.match.participants.get()
    assert participant.user_id == user.pk and participant.guest_id is None
    assert start(client, request_id).status_code == 201
    assert start(client).status_code == 409
    assert Match.objects.filter(participants__user=user, mode="singleplayer").count() == 1


@pytest.mark.parametrize("kind", ["warning", "probation"])
def test_singleplayer_remains_available_for_nonblocking_notices(
    hosted, clock, client, user, staff, kind
):
    from moderation.models import Sanction

    Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind=kind,
        category="fair_play",
        reason="Solo policy",
        starts_at=clock["now"],
    )
    client.force_login(user)
    result = start(client)
    assert result.status_code == 201
    assert guess(client, result.json()["round"]["id"], "balloon").status_code == 200


@pytest.mark.parametrize("kind", ["suspension", "closed"])
def test_blocked_cookie_session_cannot_recover_owned_solo_game(
    hosted, clock, client, user, staff, kind
):
    from moderation.models import Sanction

    client.force_login(user)
    round_id = start(client).json()["round"]["id"]
    Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind=kind,
        category="fair_play",
        reason="Solo session audit",
        starts_at=clock["now"],
    )
    assert client.get(BASE + f"rounds/{round_id}/").status_code == 404
    assert guess(client, round_id, "balloon").status_code == 404
    # The existing guest mode remains public; account/session bans are not device bans.
    assert start(APIClient()).status_code == 201
