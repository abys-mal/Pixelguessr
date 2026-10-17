from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.backends import AccountBackend
from accounts.models import User
from moderation.models import Sanction
from moderation.services import account_restrictions

pytestmark = pytest.mark.django_db


def sanction(user, staff, kind, **kwargs):
    return Sanction.objects.create(
        user=user, issued_by=staff, category="fair_play", kind=kind, reason="Test notice", **kwargs
    )


def test_warning_acknowledgment_and_expiry(client, user, staff, submission_data):
    warning = sanction(user, staff, "warning")
    assert warning.expires_at == warning.starts_at + timedelta(days=90)
    client.force_authenticate(user)
    assert (
        client.post("/api/library/submissions/", submission_data, format="json").status_code == 201
    )
    assert client.post(f"/api/moderation/sanctions/{warning.pk}/acknowledge/").status_code == 200
    assert (
        client.post("/api/library/submissions/", submission_data, format="json").status_code == 201
    )
    warning.starts_at = timezone.now() - timedelta(days=91)
    warning.save()
    assert not account_restrictions(user)["unacknowledged_warnings"]


def test_cannot_acknowledge_another_users_warning(client, user, staff):
    owner = User.objects.create_user(username="another_player", email="another-player@example.test")
    warning = sanction(owner, staff, "warning")
    client.force_authenticate(user)
    assert client.post(f"/api/moderation/sanctions/{warning.pk}/acknowledge/").status_code == 404


def test_probation_blocks_submissions_until_expiry(client, user, staff, submission_data):
    probation = sanction(
        user,
        staff,
        "probation",
        starts_at=timezone.now() - timedelta(days=2),
        expires_at=timezone.now() + timedelta(days=1),
    )
    client.force_authenticate(user)
    assert (
        client.post("/api/library/submissions/", submission_data, format="json").status_code == 403
    )
    probation.expires_at = timezone.now() - timedelta(days=1)
    probation.save()
    assert (
        client.post("/api/library/submissions/", submission_data, format="json").status_code == 201
    )


@pytest.mark.parametrize("kind", ["suspension", "closed"])
def test_sanctions_block_authentication_and_existing_sessions(client, user, staff, kind):
    client.force_login(user, backend="accounts.backends.AccountBackend")
    sanction(user, staff, kind)
    assert AccountBackend().user_can_authenticate(user) == (kind == "suspension")
    assert (client.get("/api/auth/me/").json()["user"] is None) == (kind == "closed")
    assert client.post(
        "/api/auth/login/",
        {"username": user.username, "password": "a-strong-unique-pass-734"},
        format="json",
    ).status_code == (400 if kind == "closed" else 200)


def test_closure_reversal_requires_administrator(user, staff):
    closed = sanction(user, staff, "closed")
    closed.revoked_at = timezone.now()
    closed.revoked_by = staff
    with pytest.raises(ValidationError):
        closed.save()
    staff.is_superuser = True
    staff.save()
    closed.save()
    assert not account_restrictions(user)["blocked"]


def test_report_self_rejected(client, user, staff):
    client.force_authenticate(user)
    assert (
        client.post(
            "/api/moderation/reports/",
            {"subject": str(user.pk), "category": "fair_play", "details": "Test"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/moderation/reports/",
            {"subject": str(staff.pk), "category": "fair_play", "details": "Test"},
            format="json",
        ).status_code
        == 201
    )
