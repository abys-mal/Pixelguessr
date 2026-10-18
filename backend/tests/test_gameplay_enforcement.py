import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
import test_ranked as ranked_fixtures
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.db import close_old_connections, connection
from django.utils import timezone
from rest_framework.test import APIClient
from test_parties import action, create, join
from test_ranked import pair

from accounts.models import User
from games import parties, ranked
from games.models import Match, Party, RankedQueue
from games.ranked_rules import elo_after
from moderation.enforcement import enforce_user
from moderation.models import Sanction
from moderation.services import account_restrictions

pytestmark = pytest.mark.django_db
clock = ranked_fixtures.clock
images = ranked_fixtures.images
opponent = ranked_fixtures.opponent
SOLO = "/api/games/singleplayer/"


def issue(user, staff, kind, **kwargs):
    kwargs.setdefault("starts_at", timezone.now())
    return Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind=kind,
        category="fair_play",
        reason="Public test reason",
        internal_note="PRIVATE NOTE",
        **kwargs,
    )


@pytest.mark.parametrize(
    "kind,login,solo,party,duel,upload",
    [
        ("warning", 200, 201, 201, 201, 201),
        ("probation", 200, 201, 201, 403, 403),
        ("suspension", 200, 201, 403, 403, 403),
        ("closed", 400, 403, 403, 403, 403),
    ],
)
def test_authoritative_activity_matrix(
    client, user, staff, images, uploaded_submission, kind, login, solo, party, duel, upload
):
    client.force_login(user)
    cookie = client.cookies["sessionid"].value
    issue(user, staff, kind)
    assert (
        client.post(SOLO + "rounds/", {"request_id": str(uuid.uuid4())}, format="json").status_code
        == solo
    )
    assert create(client).status_code == party
    assert (
        client.post(
            "/api/ranked/queue/", {"request_id": str(uuid.uuid4())}, format="json"
        ).status_code
        == duel
    )
    assert (
        client.post(
            "/api/library/submissions/", uploaded_submission(), format="multipart"
        ).status_code
        == upload
    )
    assert client.get("/api/auth/settings/").status_code == (403 if kind == "closed" else 200)
    assert client.cookies["sessionid"].value == cookie
    fresh = APIClient()
    response = fresh.post(
        "/api/auth/login/",
        {"username": user.username, "password": "a-strong-unique-pass-734"},
        format="json",
    )
    assert response.status_code == login
    assert "PRIVATE NOTE" not in response.content.decode()
    if kind == "closed":
        assert "Your account has been closed." in response.content.decode()
        wrong = fresh.post(
            "/api/auth/login/", {"username": user.username, "password": "wrong"}, format="json"
        )
        assert "closed" not in wrong.content.decode()


@pytest.mark.parametrize("kind", ["probation", "suspension", "closed"])
def test_commit_immediately_forfeits_duel_once(
    images, user, staff, opponent, kind, django_capture_on_commit_callbacks
):
    match = pair(user, opponent)
    with django_capture_on_commit_callbacks(execute=True):
        issue(user, staff, kind)
    match.refresh_from_db()
    assert match.status == "complete" and match.ranked_outcome == "forfeit"
    assert match.ranked_winner.user_id == opponent.pk and match.elo_applied_at
    first = match.elo_applied_at
    for _ in range(3):
        enforce_user(user.pk)
        ranked.clock_tick()
    user.refresh_from_db()
    opponent.refresh_from_db()
    match.refresh_from_db()
    assert user.ranked_losses == opponent.ranked_wins == 1
    assert user.ranked_matches == opponent.ranked_matches == 1
    assert user.rating == elo_after(1000, 1000, False, 0) == 980
    assert opponent.rating == 1020 and match.elo_applied_at == first
    assert "PRIVATE NOTE" not in str(ranked.state(opponent, match.pk))


@pytest.mark.parametrize("kind", ["probation", "suspension", "closed"])
def test_commit_removes_matchmaking_ticket(
    images, user, staff, kind, django_capture_on_commit_callbacks
):
    ranked.queue_join(user, uuid.uuid4())
    with django_capture_on_commit_callbacks(execute=True):
        issue(user, staff, kind)
    assert RankedQueue.objects.get(user=user).queued_at is None


def party_game(user, opponent):
    host, guest = APIClient(), APIClient()
    host.force_login(user)
    guest.force_login(opponent)
    code = create(host).json()["code"]
    assert join(guest, code).status_code == 200
    assert action(host, code, "start").status_code == 200
    return host, guest, Party.objects.get(code=code)


@pytest.mark.parametrize("kind", ["suspension", "closed"])
def test_host_restriction_ends_party_without_grace(
    images, user, staff, opponent, kind, django_capture_on_commit_callbacks
):
    host, guest, party = party_game(user, opponent)
    with django_capture_on_commit_callbacks(execute=True):
        issue(user, staff, kind)
    party.refresh_from_db()
    assert party.status == "aborted" and party.end_reason == (
        "host_suspended" if kind == "suspension" else "host_closed"
    )
    assert not party.members.filter(left_at__isnull=True).exists()
    match = Match.objects.get(pk=party.current_match_id)
    assert match.status == "aborted"
    assert not match.rounds.filter(reveal_started_at__isnull=False, ended_at__isnull=True).exists()
    response = guest.get(f"/api/parties/{party.code}/")
    assert response.status_code == 200 and response.json()["status"] == "aborted"
    assert kind in response.json()["end_reason"] or kind == "suspension"
    assert host.get(f"/api/parties/{party.code}/").status_code == 403


@pytest.mark.parametrize("kind", ["suspension", "closed"])
def test_nonhost_removed_without_aborting_remaining_party(
    images, user, staff, opponent, kind, django_capture_on_commit_callbacks
):
    host, guest, party = party_game(user, opponent)
    with django_capture_on_commit_callbacks(execute=True):
        issue(opponent, staff, kind)
    party.refresh_from_db()
    assert party.status == "playing"
    assert party.members.filter(user=opponent, left_at__isnull=False).exists()
    assert party.members.filter(user=user, left_at__isnull=True).exists()
    parties.clock_tick()
    response = host.get(f"/api/parties/{party.code}/")
    assert response.status_code == 200 and response.json()["status"] == "playing"
    assert "removed" in response.json()["notice"]
    assert guest.post(f"/api/parties/{party.code}/join/", {}, format="json").status_code == 403


@pytest.mark.parametrize("kind", ["warning", "probation"])
@pytest.mark.parametrize("role", ["host", "member"])
def test_warning_and_probation_leave_active_parties_intact(
    images, user, staff, opponent, kind, role, django_capture_on_commit_callbacks
):
    host, guest, party = party_game(user, opponent)
    revision = party.revision
    with django_capture_on_commit_callbacks(execute=True):
        issue(user if role == "host" else opponent, staff, kind)
    party.refresh_from_db()
    assert party.status == "playing" and party.revision == revision
    assert party.members.filter(left_at__isnull=True).count() == 2
    assert (
        host.get(f"/api/parties/{party.code}/").status_code
        == guest.get(f"/api/parties/{party.code}/").status_code
        == 200
    )


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension"])
def test_singleplayer_continues_during_restriction(
    images, user, staff, client, kind, django_capture_on_commit_callbacks
):
    client.force_login(user)
    started = client.post(SOLO + "rounds/", {"request_id": str(uuid.uuid4())}, format="json").json()
    round_id = started["round"]["id"]
    with django_capture_on_commit_callbacks(execute=True):
        issue(user, staff, kind)
    response = client.get(SOLO + f"rounds/{round_id}/")
    assert response.status_code == 200 and response.json()["round"]["id"] == round_id
    assert client.get(SOLO + f"rounds/{round_id}/image/").status_code == 200


def test_scheduled_restriction_beats_no_contest_and_round_transition(
    images, user, staff, opponent, clock
):
    match = pair(user, opponent)
    start = clock["now"]
    issue(user, staff, "probation", starts_at=start + timedelta(seconds=10))
    match.participants.update(ranked_disconnected_at=start)
    clock["now"] = start + timedelta(seconds=60)
    ranked.clock_tick()
    match.refresh_from_db()
    assert match.ranked_outcome == "forfeit" and match.ranked_winner.user_id == opponent.pk


def test_notice_priority_expiration_acknowledgment_and_privacy(user, staff, clock, client):
    client.force_login(user)
    warning = issue(user, staff, "warning")
    assert account_restrictions(user)["notice"]["kind"] == "warning"
    probation = issue(user, staff, "probation", expires_at=clock["now"] + timedelta(hours=1))
    issue(user, staff, "suspension", expires_at=clock["now"] + timedelta(minutes=30))
    assert account_restrictions(user)["notice"]["kind"] == "suspension"
    clock["now"] += timedelta(minutes=31)
    assert account_restrictions(user)["notice"]["kind"] == "probation"
    probation.revoked_at = clock["now"]
    probation.revoked_by = staff
    probation.save()
    assert account_restrictions(user)["notice"]["kind"] == "warning"
    assert client.post(f"/api/moderation/sanctions/{warning.pk}/acknowledge/").status_code == 200
    assert account_restrictions(user)["notice"] is None
    data = client.get("/api/moderation/notices/").json()
    assert len(data["sanctions"]) == 3 and "PRIVATE NOTE" not in str(data)
    assert client.post("/api/moderation/notice-login/", {}).status_code == 404


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("event", ["disconnect", "transition"])
def test_concurrent_sanction_reconciliation_applies_one_forfeit(
    images, user, staff, opponent, clock, event
):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use file-backed SQLite for writer races")
    match = pair(user, opponent)
    connection_id = uuid.uuid4()
    ranked.state(user, match.pk, connection_id=connection_id, heartbeat=True)
    barrier = Barrier(2)

    def run(operation):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if operation == "moderation":
                issue(User.objects.get(pk=user.pk), User.objects.get(pk=staff.pk), "suspension")
            elif event == "transition":
                ranked.clock_tick()
            else:
                ranked.disconnect(connection_id)
                ranked.state(User.objects.get(pk=opponent.pk), match.pk)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ["moderation", "game"]))
    match.refresh_from_db()
    user.refresh_from_db()
    opponent.refresh_from_db()
    assert match.ranked_outcome == "forfeit" and user.ranked_matches == opponent.ranked_matches == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.asyncio
async def test_live_account_socket_updates_without_refresh_and_closes_access(
    user, staff, client, clock
):
    from config.asgi import application

    def cookie():
        client.force_login(user)
        return client.cookies["sessionid"].value

    token = await database_sync_to_async(cookie)()
    socket = WebsocketCommunicator(
        application,
        "/ws/account/",
        headers=[(b"origin", b"http://localhost:5173"), (b"cookie", f"sessionid={token}".encode())],
    )
    try:
        assert (await socket.connect())[0]
        assert (await socket.receive_json_from())["state"]["user"]["id"] == str(user.pk)
        await database_sync_to_async(issue)(
            user, staff, "suspension", expires_at=clock["now"] + timedelta(minutes=1)
        )
        update = await socket.receive_json_from(timeout=2)
        assert update["state"]["user"]["id"] == str(user.pk)
        assert update["state"]["restrictions"]["notice"]["kind"] == "suspension"
        assert "PRIVATE NOTE" not in str(update)
        clock["now"] += timedelta(minutes=2)
        update = await socket.receive_json_from(timeout=2)
        assert update["state"]["restrictions"]["notice"] is None
        await database_sync_to_async(issue)(user, staff, "closed")
        update = await socket.receive_json_from(timeout=2)
        assert update["state"]["account_closed"] and update["state"]["user"] is None
        assert (await socket.receive_output(timeout=2))["code"] == 4403
    finally:
        await socket.disconnect()


def test_closed_identity_cannot_renew_ranked_presence_or_leave(images, user, staff, opponent):
    from rest_framework.exceptions import PermissionDenied

    match = pair(user, opponent)
    issue(user, staff, "closed")
    with pytest.raises(PermissionDenied, match="closed"):
        ranked.state(user, match.pk, connection_id=uuid.uuid4(), heartbeat=True)
    with pytest.raises(PermissionDenied, match="closed"):
        ranked.leave(user, match.pk)
    assert not match.rankedconnection_set.exists()
    user.refresh_from_db()
    assert user.ranked_losses == 1
