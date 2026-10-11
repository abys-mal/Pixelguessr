import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from channels.testing import WebsocketCommunicator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from games.consumers import UnavailableMatchConsumer
from games.models import GuestIdentity, Match, Participant


@pytest.mark.django_db
def test_guest_identity_constraints(user):
    match = Match.objects.create(mode="party")
    guest = GuestIdentity.objects.create(
        display_name="Guest", expires_at=timezone.now() + timedelta(days=1)
    )
    Participant.objects.create(match=match, guest=guest)
    with pytest.raises(IntegrityError), transaction.atomic():
        Participant.objects.create(match=match)
    with pytest.raises(IntegrityError), transaction.atomic():
        Participant.objects.create(match=match, guest=guest, user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Participant.objects.create(match=match, guest=guest)
    ranked = Match.objects.create(mode="ranked")
    with pytest.raises(ValidationError):
        Participant(match=ranked, guest=guest).full_clean()


def test_only_singleplayer_is_available(client):
    body = client.get("/api/modes/").json()
    assert body["gameplay_available"] is True
    assert {mode["id"] for mode in body["modes"] if mode["available"]} == {"singleplayer"}
    assert {mode["id"] for mode in body["modes"]} == {"ranked", "singleplayer", "party"}


@pytest.mark.django_db
def test_health(client):
    assert client.get("/api/health/live/").status_code == 200
    assert client.get("/api/health/ready/").status_code == 200
    with patch("core.views.cache.set", side_effect=RuntimeError("secret connection string")):
        response = client.get("/api/health/ready/")
        assert response.status_code == 503
        assert "secret" not in response.content.decode()


@pytest.mark.asyncio
async def test_scaffold_websocket_rejects_gameplay():
    communicator = WebsocketCommunicator(
        UnavailableMatchConsumer.as_asgi(), f"/ws/matches/{uuid.uuid4()}/"
    )
    connected, code = await communicator.connect()
    assert not connected and code == 4404
    await communicator.disconnect()
