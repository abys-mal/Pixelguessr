import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO

import pytest
from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.utils import timezone
from PIL import Image
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from accounts.models import User
from games import ranked
from games.models import Guess, Match, Participant, RankedConnection, RankedQueue, RoundPlayerState
from games.ranked_rules import elo_after, search_window, tier
from library.models import ImageSubmission
from library.review import review_images
from library.serializers import SubmissionSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def clock(monkeypatch):
    value = {"now": timezone.now()}
    monkeypatch.setattr(timezone, "now", lambda: value["now"])
    return value


@pytest.fixture
def images(settings, tmp_path, user, staff, category):
    settings.MEDIA_ROOT = tmp_path
    result = []
    for index in range(3):
        source = BytesIO()
        Image.new("RGB", (96, 72), (220, 80 + index, 40)).save(source, "PNG")
        serializer = SubmissionSerializer(
            data={
                "canonical_answer": f"lighthouse {index}",
                "accepted_synonyms": [f"beacon {index}"],
                "category": category.pk,
                "source": "manual",
                "license": "CC0",
                "attribution": "Original test drawing",
                "image_file": SimpleUploadedFile(
                    f"secret-{index}.png", source.getvalue(), "image/png"
                ),
            }
        )
        serializer.is_valid(raise_exception=True)
        image = serializer.save(submitted_by=user)
        review_images(ImageSubmission.objects.filter(pk=image.pk), staff, "approved")
        image.refresh_from_db()
        result.append(image)
    return result


@pytest.fixture
def opponent():
    return User.objects.create_user(
        username="opponent", email="opponent@example.com", password="test-pass"
    )


def advance(clock, seconds, heartbeat=True):
    clock["now"] += timedelta(seconds=seconds)
    if heartbeat:
        Participant.objects.filter(
            match__mode="ranked", ranked_disconnected_at__isnull=True
        ).update(ranked_last_seen=clock["now"])
        RankedConnection.objects.filter(match__isnull=False).update(last_seen=clock["now"])


def pair(user, opponent):
    ranked.queue_join(user, uuid.uuid4())
    result = ranked.queue_join(opponent, uuid.uuid4())
    return Match.objects.get(pk=result["match_id"])


@pytest.fixture
def game(images, user, opponent, clock):
    match = pair(user, opponent)
    return match


def submit(user, game, text=None, request=None):
    current = ranked.current_round(game)
    return ranked.submit(
        user, game.pk, current.pk, text or current.answer_snapshot, request or uuid.uuid4()
    )


def connect(user, game):
    cid = uuid.uuid4()
    ranked.state(user, game.pk, heartbeat=True, connection_id=cid)
    return cid


@pytest.mark.parametrize(
    "seconds,window",
    [(0, 100), (14, 100), (15, 150), (30, 250), (60, 400), (90, 600), (120, 800), (99999, 800)],
)
def test_search_windows(seconds, window):
    assert search_window(seconds) == window


@pytest.mark.parametrize(
    "rating,expected",
    [
        (100, None),
        (1000, None),
        (1199, None),
        (1200, "bronze"),
        (1399, "bronze"),
        (1400, "silver"),
        (1600, "gold"),
        (1800, "diamond"),
        (9000, "diamond"),
    ],
)
def test_tiers(rating, expected):
    assert tier(rating) == expected


@pytest.mark.parametrize(
    "rating,other,won,count,expected",
    [
        (1000, 1000, True, 0, 1020),
        (1000, 1000, False, 19, 980),
        (1000, 1000, True, 20, 1012),
        (1000, 1000, False, 20, 988),
        (100, 100, False, 0, 100),
        (1000, 1800, True, 0, 1040),
        (1000, 1800, False, 0, 1000),
        (1000000, 100, True, 0, 1000000),
    ],
)
def test_elo(rating, other, won, count, expected):
    assert elo_after(rating, other, won, count) == expected


def test_new_users_start_at_1000(opponent):
    assert opponent.rating == 1000 and opponent.ranked_matches == 0


def test_empty_library_and_guests(client, user):
    assert (
        client.post(
            "/api/ranked/queue/", {"request_id": str(uuid.uuid4())}, format="json"
        ).status_code
        == 403
    )
    client.force_authenticate(user)
    response = client.post("/api/ranked/queue/", {"request_id": str(uuid.uuid4())}, format="json")
    assert response.status_code == 503 and response.json()["code"] == "library_empty"
    assert not Match.objects.filter(mode="ranked").exists()


def test_countdown_one_guess_wrong_not_loss_and_synonym(game, user, opponent, clock):
    before = ranked.state(user, game.pk)
    assert before["round"]["status"] == "countdown" and before["round"]["revealed_count"] == 0
    assert before["round"]["completion"] is None
    with pytest.raises(APIException):
        submit(user, game)
    advance(clock, 3)
    response = submit(user, game, "totally wrong")
    assert response["result"] == "incorrect"
    assert response["state"]["round"]["status"] == "active"
    assert all(p["wins"] == 0 for p in response["state"]["players"])
    with pytest.raises(APIException):
        submit(user, game)
    current = ranked.current_round(game)
    response = submit(opponent, game, "  " + current.synonyms_snapshot[0].upper() + "!!! ")
    assert response["result"] == "correct"
    assert response["state"]["round"]["completion"]["answer"] == current.answer_snapshot
    assert response["state"]["round"]["winner_id"] == str(game.participants.get(user=opponent).pk)
    assert not Guess.objects.filter(round__match=game).exists()


def test_both_wrong_wash_and_five_second_transition(game, user, opponent, clock):
    advance(clock, 3)
    submit(user, game, "wrong")
    result = submit(opponent, game, "wrong too")["state"]
    assert result["round"]["status"] == "results" and result["round"]["winner_id"] is None
    assert all(p["wins"] == 0 for p in result["players"])
    old = result["round"]["id"]
    advance(clock, 4.9)
    assert ranked.state(user, game.pk)["round"]["id"] == old
    advance(clock, 0.1)
    new = ranked.state(user, game.pk)["round"]
    assert new["id"] != old and new["status"] == "active" and new["guessed_ids"] == []


def test_deadline_authoritative_and_no_guess_after_full_reveal(game, user, clock):
    advance(clock, 25.5)
    middle = ranked.state(user, game.pk)["round"]
    assert middle["revealed_count"] == middle["total_tiles"] // 2
    advance(clock, 22.5)
    with pytest.raises(APIException):
        submit(user, game)
    game_round = ranked.current_round(game)
    game_round.refresh_from_db()
    assert game_round.ended_at is not None and game_round.winner_id is None
    full = ranked.state(user, game.pk)["round"]
    assert full["revealed_count"] == full["total_tiles"] and full["completion"]


def test_washes_unlimited_pool_reuse_no_adjacent(game, user, opponent, clock):
    advance(clock, 3)
    image_ids = []
    for _ in range(10):
        image_ids.append(ranked.current_round(game).image_id)
        submit(user, game, "wrong")
        submit(opponent, game, "wrong")
        advance(clock, 5)
        ranked.state(user, game.pk)
    assert len(set(image_ids[:3])) == 3
    assert all(a != b for a, b in zip(image_ids, image_ids[1:], strict=False))
    game.refresh_from_db()
    assert game.status == "active" and game.rounds.count() == 11


def test_four_wins_elo_applied_once_and_history(game, user, opponent, clock, client):
    advance(clock, 3)
    for n in range(4):
        submit(user, game)
        if n < 3:
            advance(clock, 5)
            ranked.state(user, game.pk)
    final = ranked.state(user, game.pk)
    assert final["status"] == "complete" and final["outcome"] == "victory"
    assert sorted(p["wins"] for p in final["players"]) == [0, 4]
    for _ in range(3):
        ranked.clock_tick()
        ranked.leave(opponent, game.pk)
    user.refresh_from_db()
    opponent.refresh_from_db()
    assert (user.rating, user.ranked_matches, user.ranked_wins) == (1020, 1, 1)
    assert (opponent.rating, opponent.ranked_matches, opponent.ranked_losses) == (980, 1, 1)
    history = client.get(f"/api/ranked/history/{user.username}/").json()
    assert history["count"] == 1 and history["results"][0]["rating_delta"] == 20
    assert history["results"][0]["opponent"] == opponent.username


def test_leave_immediate_forfeit_does_not_disclose_unfinished_answer(game, user, opponent):
    state = ranked.leave(user, game.pk)
    assert (
        state["status"] == "complete" and state["outcome"] == "forfeit" and state["round"] is None
    )
    opponent.refresh_from_db()
    assert opponent.rating == 1020
    ranked.leave(user, game.pk)
    opponent.refresh_from_db()
    assert opponent.ranked_matches == 1


def test_disconnect_reconnect_preserves_guess_and_deadline(game, user, opponent, clock):
    first = connect(user, game)
    connect(opponent, game)
    advance(clock, 3)
    submit(user, game, "wrong")
    old = ranked.state(user, game.pk)["round"]
    ranked.disconnect(first)
    advance(clock, 20)
    restored = ranked.state(user, game.pk, heartbeat=True, connection_id=uuid.uuid4())
    assert restored["round"]["id"] == old["id"]
    assert restored["round"]["reveal_finishes_at"] == old["reveal_finishes_at"]
    assert restored["me_id"] in restored["round"]["guessed_ids"]
    assert next(p for p in restored["players"] if p["id"] == restored["me_id"])["connected"]


def test_opponent_can_win_during_disconnect_and_next_round_waits(game, user, opponent, clock):
    first = connect(user, game)
    connect(opponent, game)
    advance(clock, 3)
    ranked.disconnect(first)
    submit(opponent, game)
    advance(clock, 6)
    state = ranked.state(opponent, game.pk)
    assert state["waiting"] and state["round"]["number"] == 1
    restored = ranked.state(user, game.pk, heartbeat=True, connection_id=uuid.uuid4())
    assert restored["round"]["number"] == 2


def test_single_disconnect_deadline_forfeit(game, user, opponent, clock):
    first = connect(user, game)
    connect(opponent, game)
    ranked.disconnect(first)
    advance(clock, 29.9)
    assert ranked.state(opponent, game.pk)["status"] == "active"
    advance(clock, 0.1)
    assert ranked.state(opponent, game.pk)["outcome"] == "forfeit"
    user.refresh_from_db()
    assert user.rating == 980


@pytest.mark.parametrize("gap", [0, 1, 2])
def test_coincident_disconnect_waits_both_deadlines_no_contest(game, user, opponent, clock, gap):
    a = connect(user, game)
    b = connect(opponent, game)
    ranked.disconnect(a)
    advance(clock, gap)
    ranked.disconnect(b)
    advance(clock, 30 - gap)
    at_first = ranked.state(user, game.pk)
    if gap:
        assert at_first["status"] == "active"
    advance(clock, gap)
    final = ranked.state(user, game.pk)
    assert final["outcome"] == "no_contest" and final["winner_id"] is None
    assert all(p["rating_delta"] == 0 for p in final["players"])
    user.refresh_from_db()
    opponent.refresh_from_db()
    assert user.ranked_matches == opponent.ranked_matches == 0


@pytest.mark.parametrize("gap", [0, 2])
def test_coincident_reconnect_prevents_no_contest(game, user, opponent, clock, gap):
    a = connect(user, game)
    b = connect(opponent, game)
    ranked.disconnect(a)
    advance(clock, gap)
    ranked.disconnect(b)
    advance(clock, 20)
    ranked.state(user, game.pk, heartbeat=True, connection_id=uuid.uuid4())
    advance(clock, 10)
    final = ranked.state(user, game.pk)
    assert final["outcome"] == "forfeit" and final["winner_id"] == final["me_id"]


def test_noncoincident_both_disconnect_earliest_loses(game, user, opponent, clock):
    a = connect(user, game)
    b = connect(opponent, game)
    ranked.disconnect(a)
    advance(clock, 3)
    ranked.disconnect(b)
    advance(clock, 27, heartbeat=False)
    final = ranked.state(user, game.pk)
    assert final["outcome"] == "forfeit" and final["winner_id"] != final["me_id"]


def test_expired_reconnect_cannot_clear_no_contest_window(game, user, opponent, clock):
    a = connect(user, game)
    b = connect(opponent, game)
    ranked.disconnect(a)
    advance(clock, 2)
    ranked.disconnect(b)
    advance(clock, 28, heartbeat=False)
    with pytest.raises(APIException):
        ranked.state(user, game.pk, heartbeat=True, connection_id=uuid.uuid4())
    assert ranked.state(user, game.pk)["status"] == "active"
    advance(clock, 2, heartbeat=False)
    assert ranked.state(user, game.pk)["outcome"] == "no_contest"


def test_multiple_tabs_disconnect_only_last_connection(game, user, opponent):
    a = connect(user, game)
    b = connect(user, game)
    ranked.disconnect(a)
    assert game.participants.get(user=user).ranked_disconnected_at is None
    ranked.disconnect(b)
    assert game.participants.get(user=user).ranked_disconnected_at is not None


def test_server_restart_infers_durable_disconnect_and_recovers(game, user, clock):
    advance(clock, 43, heartbeat=False)
    ranked.clock_tick()
    assert ranked.state(user, game.pk)["outcome"] == "no_contest"


def test_queue_cancel_stale_duplicate_and_connection_close(images, user, clock):
    ticket = uuid.uuid4()
    ranked.queue_join(user, ticket)
    with pytest.raises(APIException):
        ranked.queue_join(user, uuid.uuid4())
    with pytest.raises(APIException):
        ranked.queue_state(user, uuid.uuid4(), cancel=True)
    assert ranked.queue_state(user, ticket, cancel=True)["status"] == "idle"
    with pytest.raises(APIException):
        ranked.queue_join(user, ticket)
    ticket = uuid.uuid4()
    ranked.queue_join(user, ticket)
    cid = uuid.uuid4()
    ranked.queue_connect(user, ticket, cid)
    ranked.disconnect(cid)
    assert ranked.queue_state(user)["status"] == "idle"
    ticket = uuid.uuid4()
    ranked.queue_join(user, ticket)
    advance(clock, 13)
    assert ranked.queue_state(user, ticket, heartbeat=True)["status"] == "idle"
    assert not Match.objects.filter(mode="ranked").exists()


def test_match_requires_both_actual_windows(images, user, opponent, clock):
    opponent.rating = 1200
    opponent.save()
    ranked.queue_join(user, uuid.uuid4())
    advance(clock, 30)
    RankedQueue.objects.filter(user=user).update(last_seen=clock["now"])
    assert ranked.queue_join(opponent, uuid.uuid4())["status"] == "searching"
    advance(clock, 30)
    RankedQueue.objects.update(last_seen=clock["now"])
    ranked.clock_tick()
    assert ranked.queue_state(user)["status"] == "matched"


def test_closest_candidate_oldest_first(images, user, opponent, clock):
    third = User.objects.create_user(username="third", rating=1050)
    ranked.queue_join(user, uuid.uuid4())
    # Stage candidates atomically before one matchmaking pass.
    for candidate in (opponent, third):
        RankedQueue.objects.create(
            user=candidate,
            ticket=uuid.uuid4(),
            queued_at=clock["now"] + timedelta(microseconds=1),
            last_seen=clock["now"],
            rating_snapshot=candidate.rating,
        )
    ranked.clock_tick()
    match = Match.objects.get(mode="ranked")
    assert set(match.participants.values_list("user_id", flat=True)) == {user.pk, opponent.pk}
    assert ranked.queue_state(third)["status"] == "searching"


def test_cancel_after_pair_returns_match_and_no_second_match(game, user):
    queue = RankedQueue.objects.get(user=user)
    assert ranked.queue_state(user, queue.ticket, cancel=True)["match_id"] == str(game.pk)
    with pytest.raises(APIException):
        ranked.queue_join(user, uuid.uuid4())
    assert Match.objects.filter(mode="ranked").count() == 1


def test_private_api_validation_images_and_no_answer_exposure(game, user, opponent, client, clock):
    base = f"/api/ranked/matches/{game.pk}/"
    client.force_authenticate(user)
    state = client.get(base)
    assert state.status_code == 200
    body = state.json()
    text = json.dumps(body)
    current = ranked.current_round(game)
    for secret in [
        current.answer_snapshot,
        *current.synonyms_snapshot,
        "secret-",
        "uploads/",
        "synonyms",
    ]:
        assert secret not in text
    image = client.get(body["round"]["image_url"] + "&count=400")
    assert image.status_code == 200 and image["X-Revealed-Tiles"] == "0"
    decoded = Image.open(BytesIO(image.content))
    assert len(decoded.getcolors(decoded.width * decoded.height)) == 1
    assert "no-store" in image["Cache-Control"]
    invalid = client.post(base + "guesses/", {"guess": "x"}, format="json")
    assert invalid.status_code == 400
    other = User.objects.create_user(username="outsider")
    client.force_authenticate(other)
    assert (
        client.get(base).status_code == 404
        and client.get(body["round"]["image_url"]).status_code == 404
    )
    client.force_authenticate(None)
    assert client.get(base).status_code == 403


def test_public_profile_leaderboard_pagination_ties_and_no_contest_exclusion(
    user, client, settings
):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "PAGE_SIZE": 24}
    for n in range(26):
        User.objects.create_user(
            username=f"rated{n:02}", email=f"rated{n}@example.com", rating=1300, ranked_matches=1
        )
    User.objects.filter(pk=user.pk).update(rating=1400, ranked_matches=1)
    client.force_authenticate(user)
    data = client.get("/api/ranked/leaderboard/").json()
    assert data["count"] == 27 and data["my_position"] == 1 and len(data["results"]) == 24
    assert data["results"][1]["username"] == "rated00"
    second = client.get("/api/ranked/leaderboard/?page=2").json()
    assert second["results"][0]["position"] == 25
    profile = client.get(f"/api/auth/profiles/{user.username}/").json()
    assert (
        profile["rating"] == 1400 and profile["ranked_tier"] == "silver" and "email" not in profile
    )


def test_independent_k_and_floor_forfeit(game, user, opponent):
    Participant.objects.filter(match=game, user=user).update(rated_matches_before=20)
    ranked.leave(opponent, game.pk)
    user.refresh_from_db()
    opponent.refresh_from_db()
    assert user.rating == 1012 and opponent.rating == 980


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_correct_guesses_have_one_winner(images, user, opponent, clock):
    if connection.vendor == "sqlite" and connection.settings_dict["NAME"].startswith("file:memory"):
        pytest.skip("File-backed SQLite or PostgreSQL required for real concurrent writers")
    game = pair(user, opponent)
    advance(clock, 3)
    current = ranked.current_round(game)

    def run(player):
        close_old_connections()
        try:
            ranked.submit(
                User.objects.get(pk=player.pk),
                game.pk,
                current.pk,
                current.answer_snapshot,
                uuid.uuid4(),
            )
            return True
        except APIException:
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, [user, opponent]))
    assert sum(results) == 1
    assert sum(game.participants.values_list("decisive_wins", flat=True)) == 1
    assert RoundPlayerState.objects.filter(round=current, solved_at__isnull=False).count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_websocket_auth_rejects_guest_and_untrusted_origin():
    from config.asgi import application

    for origin in (b"http://localhost:5173", b"https://evil.example"):
        socket = WebsocketCommunicator(
            application, f"/ws/matches/{uuid.uuid4()}/", headers=[(b"origin", origin)]
        )
        accepted, code = await socket.connect()
        assert not accepted and code in (4403, 1000)
        await socket.disconnect()


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension", "closed"])
def test_moderation_blocks_ranked_queue(images, user, staff, kind):
    from moderation.models import Sanction

    Sanction.objects.create(
        user=user, issued_by=staff, category="fair_play", kind=kind, reason="Test restriction"
    )
    with pytest.raises(APIException):
        ranked.queue_join(user, uuid.uuid4())
    assert not RankedQueue.objects.filter(queued_at__isnull=False).exists()


def test_players_beyond_800_never_pair(images, user, opponent, clock):
    opponent.rating = 1801
    opponent.save()
    ranked.queue_join(user, uuid.uuid4())
    ranked.queue_join(opponent, uuid.uuid4())
    advance(clock, 1000)
    RankedQueue.objects.update(last_seen=clock["now"])
    ranked.clock_tick()
    assert not Match.objects.filter(mode="ranked").exists()


def test_reused_request_uuid_and_stale_round_rejected(game, user, opponent, clock):
    advance(clock, 3)
    request = uuid.uuid4()
    current = ranked.current_round(game)
    submit(user, game, "wrong", request)
    with pytest.raises(APIException):
        submit(opponent, game, "wrong", request)
    submit(opponent, game, "wrong")
    advance(clock, 5)
    ranked.state(user, game.pk)
    with pytest.raises(APIException):
        ranked.submit(user, game.pk, current.pk, current.answer_snapshot, uuid.uuid4())
    assert (
        not ranked.current_round(game)
        .player_states.filter(ranked_guessed_at__isnull=False)
        .exists()
    )


def test_no_contest_history_visible_but_no_leaderboard_eligibility(
    game, user, opponent, clock, client
):
    a = connect(user, game)
    b = connect(opponent, game)
    ranked.disconnect(a)
    ranked.disconnect(b)
    advance(clock, 30, heartbeat=False)
    ranked.clock_tick()
    assert client.get("/api/ranked/leaderboard/").json()["count"] == 0
    row = client.get(f"/api/ranked/history/{user.username}/").json()["results"][0]
    assert row["outcome"] == "no_contest" and row["rating_delta"] == 0


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("operation", ["cancel_pair", "duplicate_pair", "completion"])
def test_concurrent_ranked_transitions(images, user, opponent, clock, operation):
    from threading import Barrier

    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for SQLite writer locks")
    barrier = Barrier(2)
    ticket = uuid.uuid4()
    if operation == "completion":
        game = pair(user, opponent)
    else:
        ranked.queue_join(user, ticket)

    def run(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if operation == "completion":
                return ranked.leave(User.objects.get(pk=user.pk), game.pk)
            if operation == "cancel_pair" and index == 0:
                return ranked.queue_state(User.objects.get(pk=user.pk), ticket, cancel=True)
            return ranked.queue_join(User.objects.get(pk=opponent.pk), uuid.uuid4())
        except APIException:
            return None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        list(workers.map(run, range(2)))
    assert Match.objects.filter(mode="ranked").count() <= 1
    if operation == "completion":
        user.refresh_from_db()
        opponent.refresh_from_db()
        assert user.ranked_matches == opponent.ranked_matches == 1
        assert (user.rating, opponent.rating) == (980, 1020)
    else:
        assert Participant.objects.filter(user=user, match__mode="ranked").count() <= 1
        assert Participant.objects.filter(user=opponent, match__mode="ranked").count() <= 1
        if not Match.objects.filter(mode="ranked").exists():
            assert RankedQueue.objects.get(user=user).queued_at is None


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_authenticated_ranked_sockets_and_session_revocation(images, user, opponent, clock):
    from channels.db import database_sync_to_async
    from django.contrib.sessions.models import Session

    from config.asgi import application

    def setup():
        game = pair(user, opponent)
        client = APIClient()
        client.force_login(user, backend="accounts.backends.AccountBackend")
        friend = APIClient()
        friend.force_login(opponent, backend="accounts.backends.AccountBackend")
        return game.pk, client.cookies["sessionid"].value, friend.cookies["sessionid"].value

    mid, cookie, friend_cookie = await database_sync_to_async(setup)()

    def socket(key):
        return WebsocketCommunicator(
            application,
            f"/ws/matches/{mid}/",
            headers=[
                (b"origin", b"http://localhost:5173"),
                (b"host", b"localhost:8000"),
                (b"cookie", f"sessionid={key}".encode()),
            ],
        )

    a, b = socket(cookie), socket(friend_cookie)
    assert (await a.connect())[0] and (await b.connect())[0]
    first = (await a.receive_json_from())["state"]
    second = (await b.receive_json_from())["state"]
    assert first["round"]["started_at"] == second["round"]["started_at"]
    assert first["round"]["completion"] is None
    await a.send_json_to({"type": "clock", "token": "latency-sample"})
    timing = await a.receive_json_from()
    assert timing == {
        "type": "clock",
        "token": "latency-sample",
        "server_now": clock["now"].isoformat(),
    }
    advance(clock, 3, heartbeat=False)
    await a.send_json_to(
        {
            "type": "guess",
            "round_id": first["round"]["id"],
            "guess": "wrong",
            "request_id": str(uuid.uuid4()),
        }
    )
    reply = await a.receive_json_from()
    assert reply["type"] == "guess_result" and reply["result"] == "incorrect"
    await database_sync_to_async(lambda: Session.objects.filter(session_key=cookie).delete())()
    while True:
        message = await a.receive_json_from(timeout=3)
        if message["type"] == "access_denied":
            break
    assert message["status"] == 403
    peer = (await b.receive_json_from(timeout=3))["state"]
    assert "wrong" not in json.dumps(peer) and peer["round"]["completion"] is None
    await a.disconnect()
    await b.disconnect()


def test_shared_reveal_frames_match_snapshots_and_cache_permissions(
    game, user, opponent, clock, client, monkeypatch
):
    from django.core.cache import cache

    from games import ranked_views

    cache.clear()
    advance(clock, 3.51)
    first = ranked.state(user, game.pk)["round"]
    advance(clock, 0.12)
    second = ranked.state(opponent, game.pk)["round"]
    assert first["revealed_tiles"] == second["revealed_tiles"]
    assert first["revealed_count"] == 4
    assert first["completion"] is None
    client.force_authenticate(user)
    calls = []
    original = ranked_views.render_reveal

    def render(*args, **kwargs):
        calls.append(kwargs["count"])
        return original(*args, **kwargs)

    monkeypatch.setattr(ranked_views, "render_reveal", render)
    # A later request still renders exactly the snapshot's prefix.
    advance(clock, 1)
    response = client.get(first["image_url"])
    assert response.status_code == 200 and response["X-Revealed-Tiles"] == "4"
    frame = Image.open(BytesIO(response.content)).convert("RGB")
    visible = set(first["revealed_tiles"])
    for i in range(400):
        if i not in visible:
            assert frame.getpixel(((i % 20) * 48 + 24, (i // 20) * 36 + 18)) == (35, 33, 48)
    client.force_authenticate(opponent)
    assert client.get(first["image_url"]).content == response.content
    assert calls == [4]
    future = first["image_url"].split("?")[0] + "?v=400"
    assert client.get(future).status_code == 400
    assert client.get(first["image_url"].split("?")[0] + "?v=invalid").status_code == 400
    client.force_authenticate(None)
    assert client.get(first["image_url"]).status_code == 403


def test_correct_completion_still_ends_immediately_before_frame_boundary(game, user, clock):
    advance(clock, 3.13)
    result = submit(user, game)["state"]["round"]
    assert result["status"] == "results" and result["revealed_count"] == 400
    assert result["next_starts_at"] == (clock["now"] + timedelta(seconds=5)).isoformat()
    advance(clock, 4.99)
    assert ranked.state(user, game.pk)["round"]["id"] == result["id"]
    advance(clock, 0.01)
    assert ranked.state(user, game.pk)["round"]["id"] != result["id"]
