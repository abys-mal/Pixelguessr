import pytest
from django.contrib.auth.models import Permission
from rest_framework.exceptions import ValidationError

from accounts.models import User
from moderation.models import Activity, Sanction
from moderation.workspace import issue, review_appeal, submit_appeal

pytestmark = pytest.mark.django_db
ROOT = "/api/moderation/workspace/"


@pytest.fixture(params=["moderator", "administrator"])
def issuer(request):
    user = User.objects.create_user(username="original_issuer", email="issuer@example.test")
    if request.param == "administrator":
        user.is_staff = user.is_superuser = True
        user.save()
    else:
        user.user_permissions.add(Permission.objects.get(codename="access_workspace"))
    return user


@pytest.fixture
def appeal(issuer, user):
    sanction = issue(issuer, user.pk, {"kind": "warning", "category": "other"})
    return submit_appeal(user, sanction.pk, "Please reconsider.")


def test_issuer_relationship_in_inbox_and_player_detail(client, issuer, appeal):
    # Names can change; the authoritative FK, not a name comparison, controls the reminder.
    issuer.username = "renamed_issuer"
    issuer.save(update_fields=["username"])
    client.force_authenticate(issuer)
    row = client.get(ROOT + "appeals/").json()["results"][0]
    assert row["reviewer_is_issuer"] is True
    detail = client.get(ROOT + f"players/{appeal.user_id}/").json()
    assert detail["appeals"][0]["reviewer_is_issuer"] is True
    other = User.objects.create_superuser(username="other_admin", email="other@example.test")
    client.force_authenticate(other)
    assert client.get(ROOT + "appeals/").json()["results"][0]["reviewer_is_issuer"] is False
    # Historical records with an unavailable issuer never infer identity from a label.
    Sanction.objects.filter(pk=appeal.sanction_id).update(issued_by=None)
    assert client.get(ROOT + "appeals/").json()["results"][0]["reviewer_is_issuer"] is False
    assert (
        client.post(
            ROOT + f"appeals/{appeal.pk}/resolve/", {"decision": "uphold"}, format="json"
        ).status_code
        == 200
    )


def test_own_uphold_requires_confirmation_without_writes(client, issuer, appeal):
    client.force_authenticate(issuer)
    url = ROOT + f"appeals/{appeal.pk}/resolve/"
    before = Activity.objects.count()
    response = client.post(url, {"decision": "uphold"}, format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "own_uphold_confirmation_required"
    appeal.refresh_from_db()
    assert appeal.status == "pending" and appeal.resolved_at is None
    assert Activity.objects.count() == before
    response = client.post(url, {"decision": "uphold", "confirm_own_uphold": True}, format="json")
    assert response.status_code == 200 and response.json()["reviewer_is_issuer"] is True
    event = Activity.objects.get(appeal=appeal, action="appeal_upheld")
    assert event.actor_id == issuer.pk and event.changes == {"closing_reason": ""}
    assert (
        client.post(
            url, {"decision": "uphold", "confirm_own_uphold": True}, format="json"
        ).status_code
        == 400
    )
    assert Activity.objects.count() == before + 1


def test_service_and_authorization_cannot_bypass_confirmation(client, issuer, appeal, user):
    with pytest.raises(ValidationError, match="confirm"):
        review_appeal(issuer, appeal.pk, "uphold")
    client.force_authenticate(user)
    assert (
        client.post(
            ROOT + f"appeals/{appeal.pk}/resolve/",
            {"decision": "uphold", "confirm_own_uphold": True},
            format="json",
        ).status_code
        == 403
    )
    appeal.refresh_from_db()
    assert appeal.status == "pending"


def test_own_reversal_has_no_extra_confirmation(client, issuer, appeal):
    client.force_authenticate(issuer)
    response = client.post(
        ROOT + f"appeals/{appeal.pk}/resolve/", {"decision": "reverse"}, format="json"
    )
    assert response.status_code == 200 and response.json()["status"] == "reversed"
    assert (
        Activity.objects.filter(appeal=appeal, action="appeal_reversed", actor=issuer).count() == 1
    )
