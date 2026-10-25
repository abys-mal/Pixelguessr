import uuid
from datetime import timedelta

import pytest
import test_ranked as ranked_fixtures
from django.contrib.auth.models import Permission
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient
from test_parties import action, create, join
from test_ranked import pair

from games import ranked
from games.models import Match, Party, RankedQueue
from moderation.models import Sanction
from moderation.services import account_restrictions, active_sanctions
from moderation.workspace import acknowledge_warning, reverse

pytestmark = pytest.mark.django_db
clock = ranked_fixtures.clock
images = ranked_fixtures.images
opponent = ranked_fixtures.opponent


def warning(user, staff, **kwargs):
    return Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind="warning",
        category="other",
        reason="Review this warning",
        starts_at=timezone.now(),
        **kwargs,
    )


def test_warning_waits_for_acknowledgment_and_retry_never_extends_expiry(user, staff, clock):
    record = warning(user, staff)
    record.expires_at = timezone.now() - timedelta(seconds=1)
    record.save()
    assert record.expires_at is None  # Arbitrary expiry cannot bypass the acknowledgment gate.
    clock["now"] += timedelta(days=365)
    assert active_sanctions(user).filter(pk=record.pk).exists()
    assert record.expires_at is None
    first = acknowledge_warning(user, record.pk)
    assert first.expires_at == clock["now"] + timedelta(days=90)
    first_ack, expiry = first.acknowledged_at, first.expires_at
    clock["now"] += timedelta(days=2)
    second = acknowledge_warning(user, record.pk)
    assert second.acknowledged_at == first_ack and second.expires_at == expiry
    assert not account_restrictions(user)["unacknowledged_warnings"]
    clock["now"] = expiry
    assert not active_sanctions(user).filter(pk=record.pk).exists()


def test_all_active_warnings_must_be_acknowledged_and_reversal_releases_gate(user, staff):
    staff.user_permissions.add(Permission.objects.get(codename="access_workspace"))
    first, second = warning(user, staff), warning(user, staff)
    acknowledge_warning(user, first.pk)
    with pytest.raises(PermissionDenied):
        ranked.eligible(user)
    reverse(staff, second.pk)
    ranked.eligible(user)
    assert not account_restrictions(user)["unacknowledged_warnings"]
    assert not active_sanctions(user).filter(pk=second.pk).exists()


def test_warning_blocks_new_entries_but_not_login_reports_or_account_support(
    client, user, staff, images, uploaded_submission
):
    record = warning(user, staff)
    client.force_login(user)
    for path, body, format in [
        ("/api/ranked/queue/", {"request_id": str(uuid.uuid4())}, "json"),
        ("/api/parties/", {"request_id": str(uuid.uuid4())}, "json"),
        ("/api/library/contributions/", uploaded_submission(), "multipart"),
        ("/api/library/submissions/", uploaded_submission(), "multipart"),
    ]:
        response = client.post(path, body, format=format)
        assert (
            response.status_code == 403
            and response.json()["code"] == "warning_acknowledgment_required"
        )
    host = APIClient()
    code = create(host).json()["code"]
    assert join(client, code).status_code == 403
    assert client.get("/api/auth/settings/").status_code == 200
    assert client.get("/api/moderation/notices/").status_code == 200
    assert (
        client.post(
            "/api/moderation/reports/",
            {"subject": str(staff.pk), "category": "other", "details": "A private report"},
            format="json",
        ).status_code
        == 201
    )
    acknowledge_warning(user, record.pk)
    assert join(client, code).status_code == 200
    assert create(client).status_code == 201
    assert (
        client.post(
            "/api/ranked/queue/", {"request_id": str(uuid.uuid4())}, format="json"
        ).status_code
        == 201
    )


def test_warning_cancels_search_but_does_not_forfeit_ongoing_duel(
    user, staff, opponent, images, clock
):
    ranked.queue_join(user, uuid.uuid4())
    first = warning(user, staff)
    assert RankedQueue.objects.get(user=user).queued_at is None
    acknowledge_warning(user, first.pk)
    game = pair(user, opponent)
    second = warning(user, staff)
    game.refresh_from_db()
    assert game.status == Match.Status.ACTIVE and game.elo_applied_at is None
    assert ranked.state(user, game.pk, heartbeat=True)["status"] == "active"
    round = game.rounds.latest("number")
    clock["now"] = round.reveal_started_at + timedelta(seconds=1)
    ranked.submit(user, game.pk, round.pk, round.answer_snapshot, uuid.uuid4())
    assert ranked.image(user, game.pk, game.rounds.latest("number").pk)
    assert active_sanctions(user).filter(pk=second.pk).exists()


def test_party_can_finish_but_cannot_start_next_game_until_acknowledged(
    client, user, staff, opponent, images
):
    host = APIClient()
    host.force_login(opponent)
    client.force_login(user)
    code = create(host).json()["code"]
    assert join(client, code).status_code == 200
    record = warning(user, staff)
    assert action(host, code, "start").status_code == 403
    acknowledge_warning(user, record.pk)
    assert action(host, code, "start").status_code == 200
    next_warning = warning(user, staff)
    party = Party.objects.get(code=code)
    assert party.status == Party.Status.PLAYING
    assert client.get(f"/api/parties/{code}/").status_code == 200
    assert join(client, code).status_code == 200  # Existing membership can reconnect.
    assert party.members.get(user=user).left_at is None
    assert active_sanctions(user).filter(pk=next_warning.pk).exists()
