import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from games.models import Guess, Match, Party, PartyMember, Round, RoundPlayerState
from games.parties import clock_tick
from games.services import score_for_reveal
from library.models import ImageSubmission
from library.review import review_images
from library.serializers import SubmissionSerializer

pytestmark = pytest.mark.django_db
BASE = "/api/parties/"


@pytest.fixture
def clock(monkeypatch):
    state = {"now": timezone.now()}
    monkeypatch.setattr(timezone, "now", lambda: state["now"])
    return state


@pytest.fixture
def images(settings, tmp_path, user, staff, category):
    settings.MEDIA_ROOT = tmp_path
    result = []
    for index in range(3):
        image = BytesIO()
        Image.new("RGB", (960, 720), (200, 80 + index, 40)).save(image, "PNG")
        serializer = SubmissionSerializer(
            data={
                "canonical_answer": f"lighthouse {index}",
                "accepted_synonyms": [f"beacon {index}"],
                "category": category.pk,
                "source": "manual",
                "license": "CC0",
                "attribution": "Original test drawing",
                "image_file": SimpleUploadedFile(
                    f"secret-{index}.png", image.getvalue(), "image/png"
                ),
            }
        )
        serializer.is_valid(raise_exception=True)
        submitted = serializer.save(submitted_by=user)
        review_images(ImageSubmission.objects.filter(pk=submitted.pk), staff, "approved")
        submitted.refresh_from_db()
        result.append(submitted)
    return result


def create(client, **extra):
    return client.post(
        BASE, {"display_name": "Host", "request_id": str(uuid.uuid4()), **extra}, format="json"
    )


def join(client, code, name="Friend", **extra):
    return client.post(BASE + code + "/join/", {"display_name": name, **extra}, format="json")


def state(client, code):
    response = client.get(BASE + code + "/")
    assert response.status_code == 200, response.content
    return response.json()


def action(client, code, name, request_id=None):
    return client.post(
        BASE + code + f"/{name}/", {"request_id": str(request_id or uuid.uuid4())}, format="json"
    )


def guess(client, code, round_id, text, request_id=None, **extra):
    return client.post(
        BASE + code + "/guesses/",
        {
            "round_id": round_id,
            "guess": text,
            "request_id": str(request_id or uuid.uuid4()),
            **extra,
        },
        format="json",
    )


@pytest.fixture
def game(client, images, clock):
    created = create(client, reveal_seconds=15, round_limit=5).json()
    other = APIClient()
    assert join(other, created["code"]).status_code == 200
    started = action(client, created["code"], "start")
    assert started.status_code == 200, started.content
    first = started.json()["round"]
    clock["now"] += timedelta(seconds=3)
    return client, other, created["code"], first["id"]


def answer(round_id):
    return Round.objects.get(pk=round_id).answer_snapshot


def test_defaults_guest_identity_create_retry(client, clock):
    request_id = str(uuid.uuid4())
    created = create(client, request_id=request_id)
    assert created.status_code == 201
    data = created.json()
    assert data["settings"] == {"reveal_seconds": 30, "round_limit": 10}
    assert len(data["code"]) == 6 and data["code"].isalnum()
    assert data["host_id"] == data["me_id"]
    assert create(client, request_id=request_id).json()["code"] == data["code"]
    assert Party.objects.count() == 1 and PartyMember.objects.count() == 1


@pytest.mark.parametrize("body", [[], None, 1, "text"])
def test_settings_reject_non_object_json(client, clock, body):
    code = create(client).json()["code"]
    response = client.generic(
        "PATCH", BASE + code + "/", data=json.dumps(body), content_type="application/json"
    )
    assert response.status_code == 400
    assert state(client, code)["settings"] == {"reveal_seconds": 30, "round_limit": 10}


@pytest.mark.parametrize("seconds,rounds", [(15, 5), (30, 10), (45, 15), (60, 20)])
def test_permitted_settings(client, seconds, rounds):
    assert create(client, reveal_seconds=seconds, round_limit=rounds).status_code == 201


@pytest.mark.parametrize(
    "extra",
    [
        {"reveal_seconds": 0},
        {"reveal_seconds": 20},
        {"reveal_seconds": 61},
        {"round_limit": 1},
        {"round_limit": 21},
        {"round_limit": -5},
        {"category": 1},
        {"max_players": 20},
    ],
)
def test_invalid_or_extra_settings(client, extra):
    assert create(client, **extra).status_code == 400
    assert not Party.objects.exists()


@pytest.mark.parametrize("name", ["a", "a" * 25, "<script>", "!!!", "a\x00b", "emoji🙂"])
def test_bad_guest_names(client, name):
    assert create(client, display_name=name).status_code == 400


def test_case_insensitive_join_duplicate_name_and_reconnect(client, clock):
    code = create(client).json()["code"]
    other = APIClient()
    joined = join(other, code.lower(), "Frieda").json()
    assert joined["code"] == code
    duplicate = APIClient()
    assert join(duplicate, code, "frieda").json()["code"] == "name_taken"
    assert join(other, code, "Changed name").json()["me_id"] == joined["me_id"]
    recovered = APIClient()
    recovered.cookies = other.cookies.copy()
    assert state(recovered, code)["me_id"] == joined["me_id"]
    assert PartyMember.objects.filter(party__code=code).count() == 2


def test_account_identity_and_disambiguation(client, user):
    code = create(client, display_name="pixelplayer").json()["code"]
    other = APIClient()
    other.force_authenticate(user)
    data = join(other, code, "Fake host", host=True).json()
    assert next(m for m in data["members"] if m["id"] == data["me_id"])["name"] == "pixelplayer (2)"
    member = PartyMember.objects.get(pk=data["me_id"])
    assert member.user_id == user.pk and member.guest_id is None
    assert data["host_id"] != data["me_id"]


def test_full_party_and_explicit_leaving(client):
    code = create(client).json()["code"]
    guests = []
    for index in range(11):
        other = APIClient()
        assert join(other, code, f"Player {index}").status_code == 200
        guests.append(other)
    assert join(APIClient(), code, "Extra").json()["code"] == "party_full"
    assert action(guests[0], code, "leave").status_code == 204
    assert join(APIClient(), code, "Extra").status_code == 200
    assert state(client, code)["members"].__len__() == 12


def test_invalid_expired_closed_and_private_party(client, clock):
    assert join(client, "MISSING").status_code == 404
    data = create(client).json()
    outsider = APIClient()
    assert outsider.get(BASE + data["code"] + "/").status_code == 404
    assert action(outsider, data["code"], "start").status_code == 404
    Party.objects.filter(code=data["code"]).update(expires_at=clock["now"] - timedelta(seconds=1))
    assert join(outsider, data["code"]).status_code == 410
    clock_tick()
    assert Party.objects.get(code=data["code"]).status == "closed"
    code = create(client).json()["code"]
    assert action(client, code, "leave").status_code == 204
    assert join(outsider, code).status_code == 410


def test_host_permissions_settings_lock_and_start_count(client, images):
    code = create(client).json()["code"]
    assert action(client, code, "start").json()["code"] == "not_enough_players"
    other = APIClient()
    join(other, code)
    assert action(other, code, "start").status_code == 403
    assert (
        other.patch(
            BASE + code + "/", {"reveal_seconds": 15, "host": True}, format="json"
        ).status_code
        == 400
    )
    assert other.patch(BASE + code + "/", {"reveal_seconds": 15}, format="json").status_code == 403
    assert (
        client.patch(
            BASE + code + "/", {"reveal_seconds": 15, "round_limit": 5}, format="json"
        ).json()["settings"]["reveal_seconds"]
        == 15
    )
    request_id = uuid.uuid4()
    assert action(client, code, "start", request_id).status_code == 200
    assert action(client, code, "start", request_id).status_code == 200
    assert Match.objects.filter(mode="party").count() == 1
    assert (
        client.patch(BASE + code + "/", {"round_limit": 10}, format="json").json()["code"]
        == "settings_locked"
    )
    assert join(APIClient(), code, "Late player").json()["code"] == "match_started"


def test_empty_library_keeps_lobby_and_can_retry(client):
    code = create(client).json()["code"]
    join(APIClient(), code)
    assert action(client, code, "start").status_code == 503
    assert state(client, code)["status"] == "lobby"
    assert not Match.objects.filter(mode="party").exists()


def test_deterministic_host_leave_and_disconnect_grace(client, clock):
    code = create(client).json()["code"]
    friend = APIClient()
    clock["now"] += timedelta(seconds=1)
    friend_id = join(friend, code, "First").json()["me_id"]
    clock["now"] += timedelta(seconds=1)
    last = APIClient()
    join(last, code, "Second")
    assert action(client, code, "leave").status_code == 204
    assert state(friend, code)["host_id"] == friend_id
    original = clock["now"]
    clock["now"] = original + timedelta(seconds=44)
    assert state(last, code)["host_id"] == friend_id
    clock["now"] = original + timedelta(seconds=46)
    new_state = state(last, code)
    assert new_state["host_id"] == new_state["me_id"]
    assert state(friend, code)["host_id"] == new_state["me_id"]
    assert PartyMember.objects.filter(party__code=code, left_at__isnull=True).count() == 2


def test_shared_countdown_order_and_private_frames(game, clock, images):
    host, friend, code, rid = game
    clock["now"] -= timedelta(seconds=1)
    assert guess(host, code, rid, answer(rid)).json()["code"] == "round_not_started"
    first, second = state(host, code), state(friend, code)
    assert first["round"] == second["round"]
    image_url = first["round"]["image_url"]
    image = host.get(image_url + "&count=400&at=999999&original=true")
    assert image.status_code == 200 and image["X-Revealed-Tiles"] == "0"
    with Image.open(BytesIO(image.content)) as pixels:
        assert len(pixels.getcolors(pixels.width * pixels.height)) == 1
    text = json.dumps(first)
    for private in [answer(rid), "beacon", "secret-", "storage", "synonyms", "reveal_order"]:
        assert private not in text
    future = Round.objects.get(match_id=first["match_id"], number=2)
    assert host.get(BASE + code + f"/rounds/{future.pk}/image/").status_code == 404
    assert guess(host, code, str(future.pk), future.answer_snapshot).status_code == 409
    assert APIClient().get(image_url).status_code == 404
    clock["now"] += timedelta(seconds=8.5)
    first, second = state(host, code), state(friend, code)
    assert first["round"]["revealed_tiles"] == second["round"]["revealed_tiles"]
    assert first["round"]["revealed_count"] == 200


def test_penalty_cooldown_replay_floor_and_spectator(game, clock):
    host, friend, code, rid = game
    request_id = uuid.uuid4()
    wrong = guess(host, code, rid, "wrong", request_id).json()
    assert wrong["result"] == "incorrect"
    assert wrong["state"]["round"]["me"]["round_score"] == -50
    assert wrong["state"]["leaderboard"][0]["total_score"] == 0
    assert guess(host, code, rid, "wrong", request_id).status_code == 200
    assert Guess.objects.filter(round_id=rid).count() == 1
    assert guess(host, code, rid, answer(rid)).json()["code"] == "guess_cooldown"
    reconnect = APIClient()
    reconnect.cookies = host.cookies.copy()
    assert guess(reconnect, code, rid, answer(rid)).json()["code"] == "guess_cooldown"
    clock["now"] += timedelta(seconds=2)
    solved = guess(host, code, rid, answer(rid)).json()["state"]
    assert solved["round"]["me"]["solved"] is True
    count = solved["round"]["revealed_count"]
    assert solved["round"]["me"]["round_score"] == score_for_reveal(count, 400) - 50
    assert solved["round"]["completion"] is None
    assert answer(rid) not in json.dumps(state(friend, code))
    assert guess(host, code, rid, "wrong").json()["code"] == "already_solved"
    assert guess(friend, code, rid, "WRONG", request_id).json()["code"] == "request_conflict"


def test_correct_synonym_and_early_end_only_once(game, clock):
    host, friend, code, rid = game
    image = Round.objects.get(pk=rid).image
    req = uuid.uuid4()
    assert (
        guess(host, code, rid, image.accepted_synonyms[0].upper() + "!!!", req).json()["result"]
        == "correct"
    )
    ended = guess(friend, code, rid, answer(rid)).json()["state"]
    assert ended["round"]["status"] == "results"
    assert ended["round"]["completion"]["answer"] == answer(rid)
    assert ended["round"]["revealed_count"] == 400
    assert all(p["total_score"] == 1000 for p in ended["leaderboard"])
    assert (
        guess(host, code, rid, image.accepted_synonyms[0].upper() + "!!!", req).status_code == 200
    )
    assert all(p["total_score"] == 1000 for p in state(host, code)["leaderboard"])
    assert guess(friend, code, rid, "wrong").json()["code"] == "round_ended"
    clock["now"] += timedelta(seconds=5)
    next_state = state(host, code)
    assert next_state["round"]["number"] == 2 and next_state["round"]["status"] == "countdown"
    assert next_state["round"]["me"]["round_score"] == 0
    assert all(p["total_score"] == 1000 for p in next_state["leaderboard"])


def test_deadline_round_final_completion_restart_and_selection(game, clock):
    host, friend, code, _ = game
    seen = []
    for number in range(1, 6):
        current = state(host, code)
        game_round = Round.objects.get(pk=current["round"]["id"])
        seen.append(game_round.image_id)
        clock["now"] = game_round.reveal_started_at + timedelta(seconds=15)
        clock_tick()
        completed = state(host, code)
        assert completed["round"]["completion"] is not None
        assert completed["round"]["me"]["round_score"] == 0
        if number < 5:
            assert completed["status"] == "playing"
            clock["now"] += timedelta(seconds=8)
        else:
            assert completed["status"] == "playing"
            clock["now"] += timedelta(seconds=5)
            clock_tick()
            completed = state(host, code)
            assert completed["status"] == "complete"
            assert len(completed["winners"]) == 2
    assert len(set(seen[:3])) == 3
    assert all(a != b for a, b in zip(seen, seen[1:], strict=False))
    match_id = completed["match_id"]
    assert action(friend, code, "lobby").json()["status"] == "lobby"
    assert client_settings(host, code, 30, 10).status_code == 200
    restarted = action(host, code, "start").json()
    assert restarted["match_id"] != match_id
    assert restarted["round"]["number"] == 1
    assert len(restarted["leaderboard"]) == 2
    assert PartyMember.objects.filter(party__code=code).count() == 2


def client_settings(client, code, seconds, rounds):
    return client.patch(
        BASE + code + "/", {"reveal_seconds": seconds, "round_limit": rounds}, format="json"
    )


def test_penalties_reduce_previous_points_and_negative_round(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    guess(friend, code, rid, answer(rid))
    clock["now"] += timedelta(seconds=8)
    second = state(host, code)["round"]["id"]
    for _ in range(3):
        assert guess(host, code, second, "wrong").status_code == 200
        clock["now"] += timedelta(seconds=2)
    assert (
        next(p for p in state(host, code)["leaderboard"] if p["id"] == state(host, code)["me_id"])[
            "total_score"
        ]
        == 850
    )
    clock["now"] = Round.objects.get(pk=second).reveal_started_at + timedelta(seconds=15)
    clock_tick()
    stored = RoundPlayerState.objects.get(
        round_id=second, participant__party_member__display_name="Host"
    )
    assert stored.score == -150 and stored.total_after == 850 and stored.finalized_at
    clock_tick()
    assert stored.participant.total_score == 850


def test_identity_impersonation_and_csrf(game):
    host, friend, code, rid = game
    host_id = state(host, code)["me_id"]
    result = guess(
        friend, code, rid, answer(rid), participant_id=host_id, player_id=host_id, host=True
    ).json()["state"]
    assert result["round"]["me"]["solved"]
    assert not state(host, code)["round"]["me"]["solved"]
    protected = APIClient(enforce_csrf_checks=True)
    assert create(protected).status_code == 403
    token = protected.get("/api/auth/csrf/").json()["csrfToken"]
    protected.credentials(HTTP_X_CSRFTOKEN=token)
    assert create(protected).status_code == 201


def test_refresh_disconnected_scores_and_server_clock(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    clock["now"] += timedelta(seconds=16)
    clock_tick()
    recovered = APIClient()
    recovered.cookies = host.cookies.copy()
    data = state(recovered, code)
    assert data["round"]["status"] == "results"
    assert data["round"]["me"]["solved"] and data["round"]["me"]["round_score"] == 1000
    assert (
        len(data["members"]) == 2
        and not next(m for m in data["members"] if m["name"] == "Friend")["connected"]
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_party_guesses_and_full_join(game):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for real SQLite writer locks.")
    host, friend, code, rid = game
    request_id = uuid.uuid4()
    cookies = host.cookies.copy()

    def submit(_):
        close_old_connections()
        client = APIClient()
        client.cookies = cookies.copy()
        try:
            return guess(client, code, rid, "wrong", request_id).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(submit, range(2))) == [200, 200]
    assert Guess.objects.filter(round_id=rid).count() == 1
    assert (
        RoundPlayerState.objects.get(
            round_id=rid, participant__party_member__display_name="Host"
        ).score
        == -50
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_websocket_membership_origin_and_private_guess(images, clock):
    from config.asgi import application

    def setup():
        host = APIClient()
        code = create(host, reveal_seconds=15, round_limit=5).json()["code"]
        other = APIClient()
        join(other, code)
        action(host, code, "start")
        return code, host.cookies[settings_cookie()].value, other.cookies[settings_cookie()].value

    def settings_cookie():
        from django.conf import settings

        return settings.SESSION_COOKIE_NAME

    code, host_cookie, friend_cookie = await database_sync_to_async(setup)()
    clock["now"] += timedelta(seconds=3)

    def communicator(cookie=None, origin=b"http://localhost:5173"):
        headers = [(b"origin", origin), (b"host", b"localhost:8000")]
        if cookie:
            headers.append((b"cookie", f"sessionid={cookie}".encode()))
        return WebsocketCommunicator(application, f"/ws/parties/{code}/", headers=headers)

    stranger = communicator()
    assert (await stranger.connect())[0] is False
    await stranger.disconnect()
    malicious = communicator(host_cookie, b"https://evil.example")
    assert (await malicious.connect())[0] is False
    await malicious.disconnect()
    host_ws, friend_ws = communicator(host_cookie), communicator(friend_cookie)
    assert (await host_ws.connect())[0] and (await friend_ws.connect())[0]
    first = await host_ws.receive_json_from()
    second = await friend_ws.receive_json_from()
    assert first["state"]["round"]["revealed_tiles"] == second["state"]["round"]["revealed_tiles"]
    rid = first["state"]["round"]["id"]
    canonical = await database_sync_to_async(answer)(rid)
    request_id = str(uuid.uuid4())
    await host_ws.send_json_to(
        {"type": "guess", "round_id": rid, "guess": canonical, "request_id": request_id}
    )
    replies = [await host_ws.receive_json_from(), await host_ws.receive_json_from()]
    acknowledgement = next(message for message in replies if message["type"] == "guess_result")
    assert acknowledgement["request_id"] == request_id and acknowledgement["result"] == "correct"
    peer_update = await friend_ws.receive_json_from()
    assert canonical not in json.dumps(peer_update)
    assert peer_update["state"]["round"]["completion"] is None
    assert any(p["solved"] for p in peer_update["state"]["leaderboard"])
    await host_ws.disconnect()
    await friend_ws.disconnect()


def test_deadline_rejection_commits_round_end(game, clock):
    host, _, code, rid = game
    clock["now"] = Round.objects.get(pk=rid).reveal_started_at + timedelta(seconds=15)
    assert guess(host, code, rid, answer(rid)).json()["code"] == "round_ended"
    assert Round.objects.get(pk=rid).ended_at == clock["now"]


def test_leave_host_during_match_keeps_deadlines_and_scores(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    assert action(host, code, "leave").status_code == 204
    data = state(friend, code)
    assert data["host_id"] == data["me_id"] and data["round"]["id"] == rid
    assert next(p for p in data["leaderboard"] if p["name"] == "Host")["total_score"] == 1000
    assert guess(friend, code, rid, answer(rid)).json()["state"]["round"]["status"] == "results"
    assert host.get(BASE + code + "/").status_code == 404


def test_paused_library_recovers_with_a_fresh_countdown(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    guess(friend, code, rid, answer(rid))
    ImageSubmission.objects.update(status="pending")
    clock["now"] += timedelta(seconds=5)
    paused = state(host, code)
    assert paused["message"] and paused["round"]["number"] == 1
    clock["now"] += timedelta(seconds=90)
    ImageSubmission.objects.update(status="approved")
    resumed = state(host, code)
    assert resumed["round"]["number"] == 2 and resumed["round"]["status"] == "countdown"
    assert resumed["round"]["started_at"] == (clock["now"] + timedelta(seconds=3)).isoformat()


def test_live_socket_identity_reloads_revoked_session(client):
    from django.contrib.sessions.models import Session
    from rest_framework.exceptions import NotFound

    from games.party_consumer import socket_state

    code = create(client).json()["code"]
    key = client.cookies["sessionid"].value
    assert socket_state(key, code)["code"] == code
    Session.objects.filter(session_key=key).delete()
    with pytest.raises(NotFound):
        socket_state(key, code)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("operation", ["start", "correct", "join"])
def test_concurrent_party_transitions(client, images, clock, operation):
    from threading import Barrier

    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for real SQLite writer locks.")
    code = create(client, reveal_seconds=15, round_limit=5).json()["code"]
    friend = APIClient()
    join(friend, code)
    if operation == "join":
        for index in range(9):
            join(APIClient(), code, f"Player {index}")
    elif operation == "correct":
        rid = action(client, code, "start").json()["round"]["id"]
        clock["now"] += timedelta(seconds=3)
        canonical = answer(rid)
    barrier = Barrier(2)
    cookies = client.cookies.copy()

    def run(index):
        close_old_connections()
        worker = APIClient()
        if operation != "join":
            worker.cookies = cookies.copy()
        try:
            barrier.wait(timeout=10)
            if operation == "start":
                return action(worker, code, "start").status_code
            if operation == "correct":
                return guess(worker, code, rid, canonical).status_code
            return join(worker, code, f"New {index}").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(run, [0, 1]))
    assert results == [200, 409]
    if operation == "join":
        assert PartyMember.objects.filter(party__code=code, left_at__isnull=True).count() == 12
    elif operation == "start":
        assert Match.objects.filter(mode="party").count() == 1
    else:
        assert Guess.objects.filter(round_id=rid).count() == 1
        assert (
            RoundPlayerState.objects.get(
                round_id=rid, participant__party_member__display_name="Host"
            ).score
            == 1000
        )
