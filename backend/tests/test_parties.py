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


def advance_time(clock, seconds=0, *, at=None, heartbeat=True):
    clock["now"] = at if at is not None else clock["now"] + timedelta(seconds=seconds)
    if heartbeat:
        # Gameplay timing tests model clients sending their normal presence heartbeats.
        PartyMember.objects.filter(left_at__isnull=True).update(last_seen=clock["now"])


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
    advance_time(clock, 3)
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


def test_automatic_guest_names_unique_persistent_and_client_names_ignored(
    client, clock, monkeypatch
):
    monkeypatch.setattr("games.parties.secrets.randbelow", lambda limit: 3821)
    data = create(client, display_name="Chosen name").json()
    code = data["code"]
    assert data["members"][0]["name"] == "Guest 4821"
    other = APIClient()
    joined = join(other, code.lower(), "Guest 4821").json()
    assert sorted(m["name"] for m in joined["members"]) == ["Guest 4821", "Guest 4822"]
    assert join(other, code, "Changed name").json()["me_id"] == joined["me_id"]
    recovered = APIClient()
    recovered.cookies = other.cookies.copy()
    assert state(recovered, code)["members"] == joined["members"]
    assert PartyMember.objects.filter(party__code=code).count() == 2


def test_account_identity_and_disambiguation(client, user):
    client.force_authenticate(user)
    code = create(client, display_name="Fake name").json()["code"]
    from accounts.models import User

    second = User.objects.create_user(username="second-player", display_name="pixelplayer")
    other = APIClient()
    other.force_authenticate(second)
    data = join(other, code, "Fake host", host=True).json()
    assert next(m for m in data["members"] if m["id"] == data["me_id"])["name"] == "pixelplayer (2)"
    member = PartyMember.objects.get(pk=data["me_id"])
    assert member.user_id == second.pk and member.guest_id is None
    assert data["host_id"] != data["me_id"]
    user.refresh_from_db()
    assert user.display_name == ""


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


def test_host_leaving_lobby_closes_without_succession(client, clock):
    created = create(client).json()
    code = created["code"]
    friend = APIClient()
    join(friend, code)
    assert action(client, code, "leave").status_code == 204
    data = state(friend, code)
    assert data["status"] == "closed" and data["end_reason"] == "host_left"
    assert data["host_id"] == created["host_id"]
    assert join(APIClient(), code).status_code == 410


def test_shared_countdown_order_and_private_frames(game, clock, images):
    host, friend, code, rid = game
    advance_time(clock, -1)
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
    advance_time(clock, 8.5)
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
    advance_time(clock, 2)
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
    advance_time(clock, 5)
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
        advance_time(clock, at=game_round.reveal_started_at + timedelta(seconds=15))
        clock_tick()
        completed = state(host, code)
        assert completed["round"]["completion"] is not None
        assert completed["round"]["me"]["round_score"] == 0
        if number < 5:
            assert completed["status"] == "playing"
            advance_time(clock, 8)
        else:
            assert completed["status"] == "playing"
            advance_time(clock, 5)
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
    advance_time(clock, 8)
    second = state(host, code)["round"]["id"]
    for _ in range(3):
        assert guess(host, code, second, "wrong").status_code == 200
        advance_time(clock, 2)
    assert (
        next(p for p in state(host, code)["leaderboard"] if p["id"] == state(host, code)["me_id"])[
            "total_score"
        ]
        == 850
    )
    advance_time(clock, at=Round.objects.get(pk=second).reveal_started_at + timedelta(seconds=15))
    clock_tick()
    stored = RoundPlayerState.objects.get(
        round_id=second, participant__party_member_id=Party.objects.get(code=code).host_id
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


def test_refresh_recovers_scores_without_duplicate_members(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    advance_time(clock, 14)
    recovered = APIClient()
    recovered.cookies = host.cookies.copy()
    data = state(recovered, code)
    assert data["round"]["me"]["solved"] and data["round"]["me"]["round_score"] == 1000
    assert len(data["members"]) == 2
    assert PartyMember.objects.filter(party__code=code).count() == 2


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
            round_id=rid, participant__party_member_id=Party.objects.get(code=code).host_id
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
    advance_time(clock, 3, heartbeat=False)

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
    advance_time(clock, at=Round.objects.get(pk=rid).reveal_started_at + timedelta(seconds=15))
    assert guess(host, code, rid, answer(rid)).json()["code"] == "round_ended"
    assert Round.objects.get(pk=rid).ended_at == clock["now"]


def test_explicit_host_departure_aborts_and_preserves_earned_score(game, clock):
    host, friend, code, rid = game
    host_id = state(host, code)["me_id"]
    guess(host, code, rid, answer(rid))
    assert action(host, code, "leave").status_code == 204
    data = state(friend, code)
    assert data["status"] == "aborted" and data["end_reason"] == "host_left"
    assert data["host_id"] == host_id and data["round"] is None and not data["winners"]
    match = Match.objects.get(pk=data["match_id"])
    assert match.status == "aborted" and match.party_abort_reason == "host_left"
    assert match.participants.get(party_member_id=host_id).total_score == 1000
    assert guess(friend, code, rid, answer(rid)).json()["code"] == "match_aborted"
    advance_time(clock, 300, heartbeat=False)
    clock_tick()
    assert state(friend, code)["status"] == "aborted"
    assert match.rounds.filter(reveal_started_at__isnull=False).count() == 1
    assert Round.objects.get(pk=rid).ended_at is None
    assert host.get(BASE + code + "/").status_code == 404


def test_paused_library_recovers_with_a_fresh_countdown(game, clock):
    host, friend, code, rid = game
    guess(host, code, rid, answer(rid))
    guess(friend, code, rid, answer(rid))
    ImageSubmission.objects.update(status="pending")
    advance_time(clock, 5)
    paused = state(host, code)
    assert paused["message"] and paused["round"]["number"] == 1
    advance_time(clock, 90)
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
        advance_time(clock, 3)
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
                round_id=rid, participant__party_member_id=Party.objects.get(code=code).host_id
            ).score
            == 1000
        )


def kick(client, code, target, *, ban=False, request_id=None):
    return client.post(
        BASE + code + "/kick/",
        {
            "target_id": str(target),
            "prevent_rejoin": ban,
            "request_id": str(request_id or uuid.uuid4()),
        },
        format="json",
    )


@pytest.mark.parametrize("ban", [False, True])
def test_host_kick_and_party_scoped_identity_ban(client, clock, ban):
    created = create(client).json()
    code = created["code"]
    friend = APIClient()
    friend_id = join(friend, code).json()["me_id"]
    request_id = uuid.uuid4()
    assert kick(client, code, friend_id, ban=ban, request_id=request_id).status_code == 200
    removed = PartyMember.objects.get(pk=friend_id)
    assert removed.left_at and removed.departure_reason == "kicked"
    assert bool(removed.banned_at) == ban
    rejected = friend.get(BASE + code + "/")
    assert rejected.status_code == 403
    assert rejected.json()["code"] == ("party_banned" if ban else "party_removed")
    recovered = APIClient()
    recovered.cookies = friend.cookies.copy()
    assert recovered.get(BASE + code + "/").status_code == 403
    if ban:
        assert join(recovered, code).status_code == 403
        another = create(recovered).json()
        assert another["status"] == "lobby"
        assert another["code"] != code
    else:
        resumed = join(recovered, code).json()
        assert resumed["me_id"] == friend_id
        assert len(resumed["members"]) == 2
        # A lost kick acknowledgment must not kick the newly rejoined member a second time.
        assert kick(client, code, friend_id, request_id=request_id).status_code == 200
        assert state(recovered, code)["me_id"] == friend_id
    assert kick(client, code, friend_id, ban=ban, request_id=request_id).status_code == 200


def test_registered_ban_uses_account_identity_across_sessions(client, user):
    code = create(client).json()["code"]
    friend = APIClient()
    friend.force_authenticate(user)
    member_id = join(friend, code).json()["me_id"]
    assert kick(client, code, member_id, ban=True).status_code == 200
    another_browser = APIClient()
    another_browser.force_authenticate(user)
    assert join(another_browser, code, "Other name").json()["code"] == "party_banned"
    user.refresh_from_db()
    assert user.display_name == ""


def test_kick_permissions_target_validation_and_csrf(client, clock):
    created = create(client).json()
    code = created["code"]
    friend = APIClient()
    friend_id = join(friend, code).json()["me_id"]
    assert kick(friend, code, created["me_id"]).status_code == 403
    assert kick(client, code, created["me_id"]).json()["code"] == "cannot_kick_host"
    assert kick(client, code, uuid.uuid4()).status_code == 404
    elsewhere = create(APIClient()).json()
    assert kick(client, code, elsewhere["me_id"]).status_code == 404
    protected = APIClient(enforce_csrf_checks=True)
    protected.cookies = client.cookies.copy()
    assert kick(protected, code, friend_id).status_code == 403
    assert len(state(client, code)["members"]) == 2


def test_kicked_member_cannot_guess_or_read_image_or_act(client, images, clock):
    host = client
    code = create(host, reveal_seconds=60, round_limit=5).json()["code"]
    friend, third = APIClient(), APIClient()
    join(friend, code)
    join(third, code)
    rid = action(host, code, "start").json()["round"]["id"]
    advance_time(clock, 3)
    friend_id = state(friend, code)["me_id"]
    assert kick(host, code, friend_id).status_code == 200
    assert state(host, code)["status"] == "playing"
    assert guess(friend, code, rid, answer(rid)).json()["code"] == "party_removed"
    assert friend.get(BASE + code + f"/rounds/{rid}/image/").status_code == 403
    assert action(friend, code, "start").status_code == 403
    assert join(friend, code).status_code == 409
    assert Guess.objects.filter(round_id=rid).count() == 0


@pytest.mark.parametrize("cause", ["leave", "kick"])
@pytest.mark.parametrize("intermission", [False, True])
def test_last_opponent_departure_aborts_even_during_intermission(game, clock, cause, intermission):
    host, friend, code, rid = game
    if intermission:
        guess(host, code, rid, answer(rid))
        guess(friend, code, rid, answer(rid))
    before = list(
        Match.objects.get(
            pk=Party.objects.get(code=code).current_match_id
        ).participants.values_list("total_score", flat=True)
    )
    friend_id = state(friend, code)["me_id"]
    response = action(friend, code, "leave") if cause == "leave" else kick(host, code, friend_id)
    assert response.status_code == (204 if cause == "leave" else 200)
    data = state(host, code)
    assert data["status"] == "aborted" and data["end_reason"] == "not_enough_players"
    match = Match.objects.get(pk=data["match_id"])
    assert match.status == "aborted" and match.party_abort_reason == "not_enough_players"
    advance_time(clock, 120, heartbeat=False)
    clock_tick()
    assert state(host, code)["status"] == "aborted"
    assert match.rounds.filter(reveal_started_at__isnull=False).count() == 1
    assert list(match.participants.values_list("total_score", flat=True)) == before
    assert action(host, code, "lobby").status_code == 409
    assert action(host, code, "start").status_code == 409
    assert host.get(BASE + code + f"/rounds/{rid}/image/").status_code == 404


def test_brief_host_disconnect_reconnect_then_grace_expiry(game, clock):
    host, friend, code, rid = game
    original = state(host, code)
    friend_id = state(friend, code)["me_id"]
    advance_time(clock, 14.999, heartbeat=False)
    # Keep the other player present; the host reconnects immediately before expiry.
    PartyMember.objects.filter(pk=friend_id).update(last_seen=clock["now"])
    recovered = APIClient()
    recovered.cookies = host.cookies.copy()
    assert state(recovered, code)["round"]["id"] == rid
    assert Party.objects.get(code=code).status == "playing"
    advance_time(clock, 15.001, heartbeat=False)
    PartyMember.objects.filter(pk=friend_id).update(last_seen=clock["now"])
    clock_tick()
    data = state(friend, code)
    assert data["status"] == "aborted" and data["end_reason"] == "host_disconnected"
    assert data["host_id"] == original["host_id"]
    # Even a late host heartbeat cannot resurrect the match.
    assert state(recovered, code)["status"] == "aborted"
    assert PartyMember.objects.filter(party__code=code).count() == 2


def test_lobby_host_disconnect_grace_closes_party(client, clock):
    created = create(client).json()
    code = created["code"]
    friend = APIClient()
    joined = join(friend, code).json()
    advance_time(clock, 14, heartbeat=False)
    assert state(friend, code)["status"] == "lobby"
    advance_time(clock, 2, heartbeat=False)
    data = state(friend, code)
    assert data["status"] == "closed" and data["end_reason"] == "host_disconnected"
    assert data["host_id"] == created["host_id"] and data["me_id"] == joined["me_id"]
    assert join(APIClient(), code).status_code == 410


def test_last_opponent_disconnect_recovers_during_grace_then_aborts(game, clock):
    host, friend, code, rid = game
    host_id = state(host, code)["me_id"]
    advance_time(clock, 14, heartbeat=False)
    PartyMember.objects.filter(pk=host_id).update(last_seen=clock["now"])
    assert state(host, code)["status"] == "playing"
    assert state(friend, code)["round"]["id"] == rid
    assert PartyMember.objects.filter(party__code=code, left_at__isnull=True).count() == 2
    advance_time(clock, 16, heartbeat=False)
    PartyMember.objects.filter(pk=host_id).update(last_seen=clock["now"])
    clock_tick()
    assert state(host, code)["end_reason"] == "not_enough_players"
    assert friend.get(BASE + code + "/").status_code == 403
    assert guess(host, code, rid, answer(rid)).json()["code"] == "match_aborted"


def test_two_simultaneous_opponent_disconnects_abort_without_host_transfer(client, images, clock):
    code = create(client, reveal_seconds=60, round_limit=5).json()["code"]
    join(APIClient(), code)
    join(APIClient(), code)
    started = action(client, code, "start").json()
    advance_time(clock, 16, heartbeat=False)
    PartyMember.objects.filter(pk=started["me_id"]).update(last_seen=clock["now"])
    clock_tick()
    ended = state(client, code)
    assert ended["status"] == "aborted" and ended["host_id"] == started["host_id"]
    assert len(ended["members"]) == 1


def test_solved_spectators_count_and_three_players_can_continue_after_leave(client, images, clock):
    code = create(client, reveal_seconds=60, round_limit=5).json()["code"]
    friend, third = APIClient(), APIClient()
    join(friend, code)
    join(third, code)
    rid = action(client, code, "start").json()["round"]["id"]
    advance_time(clock, 3)
    assert guess(friend, code, rid, answer(rid)).status_code == 200
    assert action(third, code, "leave").status_code == 204
    assert state(client, code)["status"] == "playing"
    assert guess(client, code, rid, answer(rid)).json()["state"]["round"]["status"] == "results"
    assert state(friend, code)["status"] == "playing"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_existing_socket_removed_notice_and_banned_reconnect(images, clock):
    from config.asgi import application

    def setup():
        host, friend = APIClient(), APIClient()
        code = create(host).json()["code"]
        member = join(friend, code).json()["me_id"]
        return host, code, member, friend.cookies["sessionid"].value

    host, code, member, cookie = await database_sync_to_async(setup)()
    headers = [
        (b"origin", b"http://localhost:5173"),
        (b"host", b"localhost:8000"),
        (b"cookie", f"sessionid={cookie}".encode()),
    ]
    ws = WebsocketCommunicator(application, f"/ws/parties/{code}/", headers=headers)
    assert (await ws.connect())[0]
    assert (await ws.receive_json_from())["type"] == "state"
    assert (await database_sync_to_async(kick)(host, code, member, ban=True)).status_code == 200
    notice = await ws.receive_json_from()
    assert notice["type"] == "access_denied" and notice["code"] == "party_banned"
    assert (await ws.receive_output())["code"] == 4403
    await ws.disconnect()
    reconnect = WebsocketCommunicator(application, f"/ws/parties/{code}/", headers=headers)
    assert (await reconnect.connect())[0] is False
    await reconnect.disconnect()


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("race", ["host_leave_guess", "ban_reconnect", "abort_deadline"])
def test_departure_races_remain_terminal_and_idempotent(client, images, clock, race):
    from threading import Barrier

    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for real SQLite writer locks.")
    code = create(client, reveal_seconds=60, round_limit=5).json()["code"]
    friend = APIClient()
    friend_id = join(friend, code).json()["me_id"]
    rid = None
    if race != "ban_reconnect":
        rid = action(client, code, "start").json()["round"]["id"]
        advance_time(clock, 3)
        canonical = answer(rid)
    if race == "abort_deadline":
        advance_time(clock, 60)
    barrier = Barrier(2)

    def run(index):
        close_old_connections()
        worker = APIClient()
        worker.cookies = (client if index == 0 else friend).cookies.copy()
        try:
            barrier.wait(timeout=10)
            if race == "ban_reconnect":
                return (
                    kick(worker, code, friend_id, ban=True).status_code
                    if index == 0
                    else join(worker, code).status_code
                )
            if index == 0:
                return action(worker, code, "leave").status_code
            if race == "abort_deadline":
                return worker.get(BASE + code + "/").status_code
            return guess(worker, code, rid, canonical).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    if race == "ban_reconnect":
        assert results[0] == 200 and results[1] in (200, 403)
        assert PartyMember.objects.get(pk=friend_id).banned_at
        assert join(friend, code).status_code == 403
    else:
        assert results[0] == 204 and results[1] in (200, 409)
        party = Party.objects.get(code=code)
        assert party.status == "aborted" and party.end_reason == "host_left"
        assert party.current_match.status == "aborted"
        advance_time(clock, 200, heartbeat=False)
        clock_tick()
        assert party.current_match.rounds.filter(reveal_started_at__isnull=False).count() == 1
        assert guess(friend, code, rid, canonical).status_code == 409


def test_guess_that_expires_opponent_membership_commits_departure(client, images, clock):
    code = create(client, reveal_seconds=60, round_limit=5).json()["code"]
    friend, third = APIClient(), APIClient()
    friend_id = join(friend, code).json()["me_id"]
    join(third, code)
    rid = action(client, code, "start").json()["round"]["id"]
    advance_time(clock, 16)
    PartyMember.objects.filter(pk=friend_id).update(last_seen=clock["now"] - timedelta(seconds=16))
    response = guess(friend, code, rid, answer(rid))
    assert response.status_code == 403
    assert PartyMember.objects.get(pk=friend_id).departure_reason == "disconnected"
    assert Party.objects.get(code=code).status == "playing"
    assert not Guess.objects.filter(round_id=rid).exists()


def test_guess_that_triggers_host_timeout_commits_abort(game, clock):
    host, friend, code, rid = game
    friend_id = state(friend, code)["me_id"]
    advance_time(clock, 16, heartbeat=False)
    PartyMember.objects.filter(pk=friend_id).update(last_seen=clock["now"])
    response = guess(friend, code, rid, answer(rid))
    assert response.json()["code"] == "match_aborted"
    party = Party.objects.get(code=code)
    assert party.status == "aborted" and party.current_match.status == "aborted"
    assert Round.objects.get(pk=rid).ended_at is None


def test_expiring_third_player_leaves_solved_spectators_eligible(client, images, clock):
    code = create(client, reveal_seconds=60, round_limit=5).json()["code"]
    friend, third = APIClient(), APIClient()
    join(friend, code)
    third_id = join(third, code).json()["me_id"]
    rid = action(client, code, "start").json()["round"]["id"]
    advance_time(clock, 3)
    guess(client, code, rid, answer(rid))
    guess(friend, code, rid, answer(rid))
    assert state(client, code)["round"]["status"] == "active"
    advance_time(clock, 16)
    PartyMember.objects.filter(pk=third_id).update(last_seen=clock["now"] - timedelta(seconds=16))
    result = state(client, code)
    assert result["status"] == "playing" and result["round"]["status"] == "results"
    assert len(result["members"]) == 2


def test_registered_party_creation_uses_cookie_session_identity(client, user):
    client.force_login(user, backend="accounts.backends.AccountBackend")
    response = create(client)
    assert response.status_code == 201
    party = Party.objects.get(code=response.json()["code"])
    assert party.host.user_id == user.pk
    assert party.host.guest_id is None


@pytest.mark.parametrize("kind", ["warning", "suspension", "closed"])
def test_active_party_sanction_enforces_host_restrictions_without_grace(
    client, images, user, staff, clock, kind
):
    from moderation.models import Sanction

    client.force_login(user)
    created = create(client).json()
    code = created["code"]
    other = APIClient()
    assert join(other, code).status_code == 200
    round_id = action(client, code, "start").json()["round"]["id"]
    advance_time(clock, 3)
    Sanction.objects.create(
        user=user, issued_by=staff, kind=kind, category="fair_play", reason="Party audit"
    )
    if kind == "warning":
        assert client.get(BASE + code + "/").status_code == 200
        assert guess(client, code, round_id, answer(round_id)).status_code == 200
        return
    assert client.get(BASE + code + "/").status_code in [403, 404]
    assert guess(client, code, round_id, answer(round_id)).status_code in [403, 404]
    assert client.get(BASE + code + f"/rounds/{round_id}/image/").status_code in [403, 404]
    assert not Guess.objects.filter(round_id=round_id).exists()
    clock_tick()
    result = state(other, code)
    assert (
        result["status"] == "aborted"
        and result["end_reason"] == f"host_{'suspended' if kind == 'suspension' else 'closed'}"
    )
    user.refresh_from_db()
    assert user.rating == 1000


def test_probation_preserves_party_access_under_existing_policy(client, user, staff):
    from moderation.models import Sanction

    Sanction.objects.create(
        user=user, issued_by=staff, kind="probation", category="fair_play", reason="Party policy"
    )
    client.force_login(user)
    assert create(client).status_code == 201
