import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import close_old_connections, connection
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from accounts.models import User
from moderation.models import Activity, Appeal, Report, Sanction
from moderation.services import account_restrictions
from moderation.workspace import (
    change_access,
    change_names,
    eligibility,
    issue,
    reverse,
    review_appeal,
    submit_appeal,
)

pytestmark = pytest.mark.django_db
ROOT = "/api/moderation/workspace/"


@pytest.fixture
def moderator(db):
    user = User.objects.create_user(
        username="native_mod", email="native@example.test", password="native-password-341!"
    )
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="moderation", codename="access_workspace")
    )
    return User.objects.get(pk=user.pk)


@pytest.fixture
def administrator(db):
    return User.objects.create_superuser(
        username="native_admin", email="native-admin@example.test", password="native-admin-341!"
    )


def authenticate(client, user):
    client.force_authenticate(user)


@pytest.mark.parametrize(
    "values",
    [
        {"username": "Renamed.Player"},
        {"display_name": "New public name"},
        {"username": "Renamed.Player", "display_name": "New public name"},
        {"display_name": ""},
    ],
)
def test_player_names_changes_only_requested_fields(client, moderator, user, values):
    user.display_name = "Original name"
    user.save(update_fields=["display_name"])
    before = dict(User.objects.filter(pk=user.pk).values().get())
    authenticate(client, moderator)
    response = client.post(ROOT + f"players/{user.pk}/names/", values, format="json")
    assert response.status_code == 200
    after = User.objects.filter(pk=user.pk).values().get()
    assert after == {**before, **values}
    audit = Activity.objects.get(action="player_names_changed")
    assert audit.user_id == user.pk and audit.actor_id == moderator.pk and audit.created_at
    assert audit.changes == {
        field: {"old": before[field], "new": value} for field, value in values.items()
    }


@pytest.mark.parametrize("values", [{}, {"username": "pixelplayer", "display_name": ""}])
def test_player_names_noop_has_no_audit_or_notification(moderator, user, values, monkeypatch):
    notification = Mock()
    monkeypatch.setattr("moderation.enforcement.schedule", notification)
    change_names(moderator, user.pk, values)
    assert not Activity.objects.exists()
    notification.assert_not_called()


@pytest.mark.parametrize(
    "value", ["", "x" * 151, "bad name", "bad\tname", "bad_", "bad-", "bad/name", "bad!name"]
)
def test_player_names_reuses_registration_validation(client, moderator, user, value):
    from accounts.serializers import RegisterSerializer

    registration = RegisterSerializer(data={"username": value})
    assert not registration.is_valid() and "username" in registration.errors
    authenticate(client, moderator)
    response = client.post(
        ROOT + f"players/{user.pk}/names/",
        {"username": value, "display_name": "Must roll back"},
        format="json",
    )
    assert response.status_code == 400 and "username" in response.json()
    user.refresh_from_db()
    assert user.username == "pixelplayer" and user.display_name == ""
    assert not Activity.objects.exists()


@pytest.mark.parametrize("value", ["admin", "a", "Ｆｕｌｌｗｉｄｔｈ"])
def test_player_names_normalizes_and_matches_current_registration_rules(moderator, user, value):
    from accounts.serializers import available_username

    expected = available_username(value)
    updated = change_names(moderator, user.pk, {"username": value})
    assert updated.username == expected
    assert Activity.objects.get().changes == {"username": {"old": "pixelplayer", "new": expected}}


def test_player_names_rejects_case_insensitive_collision(client, moderator, user):
    authenticate(client, moderator)
    response = client.post(
        ROOT + f"players/{user.pk}/names/", {"username": moderator.username.upper()}, format="json"
    )
    assert response.status_code == 400 and "unavailable" in response.json()["username"][0]
    assert not Activity.objects.exists()


@pytest.mark.parametrize(
    "values",
    [
        {"display_name": "x" * 41},
        {"email": "no@example.test"},
        {"rating": 9999},
        {"id": str(uuid.uuid4())},
    ],
)
def test_player_names_rejects_invalid_display_and_other_fields(client, moderator, user, values):
    authenticate(client, moderator)
    assert client.post(ROOT + f"players/{user.pk}/names/", values, format="json").status_code == 400
    assert not Activity.objects.exists()


@pytest.mark.parametrize("role", ["guest", "player", "inactive", "closed"])
def test_player_names_denies_unauthorized_actor(client, moderator, administrator, user, role):
    if role == "player":
        authenticate(client, user)
    elif role != "guest":
        if role == "inactive":
            moderator.is_active = False
            moderator.save(update_fields=["is_active"])
        else:
            issue(administrator, moderator.pk, {"kind": "closed", "category": "integrity"})
        authenticate(client, moderator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/names/", {"username": "Renamed"}, format="json"
        ).status_code
        == 403
    )
    assert not Activity.objects.filter(action="player_names_changed").exists()


@pytest.mark.parametrize("role", ["staff", "moderator", "administrator"])
def test_player_names_protected_accounts_require_administrator(
    client, moderator, administrator, staff, role
):
    target = {"staff": staff, "moderator": moderator, "administrator": administrator}[role]
    authenticate(client, moderator)
    url = ROOT + f"players/{target.pk}/names/"
    assert client.post(url, {"username": "ProtectedRenamed"}, format="json").status_code == 403
    authenticate(client, administrator)
    assert client.post(url, {"username": "ProtectedRenamed"}, format="json").status_code == 200
    assert Activity.objects.get(action="player_names_changed").user_id == target.pk


def test_player_names_preserves_session_history_restrictions_and_private_audit(
    client, moderator, user
):
    from accounts.consumer import read_status
    from games.models import Match, Participant

    warning = sanction(moderator, user)
    appeal = submit_appeal(user, warning.pk, "Please review")
    report = Report.objects.create(
        subject=user, reporter=moderator, category="fair_play", details="Test report"
    )
    match = Match.objects.create(mode="ranked", status="complete", completed_at=timezone.now())
    participant = Participant.objects.create(
        match=match, user=user, rating_before=1300, rating_after=1320, rating_delta=20
    )
    user.rating = 1320
    user.ranked_matches = 1
    user.save(update_fields=["rating", "ranked_matches"])
    restrictions = account_restrictions(user)
    logged_in = APIClient()
    logged_in.force_login(user)
    session_key = logged_in.session.session_key
    authenticate(client, moderator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/names/",
            {"username": "Renamed", "display_name": "Fresh name"},
            format="json",
        ).status_code
        == 200
    )
    assert logged_in.session.session_key == session_key
    body = logged_in.get("/api/auth/me/").json()
    assert body["user"]["id"] == str(user.pk) and body["user"]["username"] == "Renamed"
    assert body["user"]["display_name"] == "Fresh name"
    assert read_status(session_key)[1]["user"]["username"] == "Renamed"
    user.refresh_from_db()
    assert user.rating == 1320 and account_restrictions(user) == restrictions
    for record in [warning, appeal, participant]:
        record.refresh_from_db()
        assert record.user_id == user.pk
    report.refresh_from_db()
    assert report.subject_id == user.pk
    public = logged_in.get("/api/auth/profiles/Renamed/").json()
    assert public["display_name"] == "Fresh name" and "activity" not in public
    assert logged_in.get(ROOT + f"players/{user.pk}/").status_code == 403
    audit = Activity.objects.get(action="player_names_changed")
    change_names(moderator, user.pk, {"username": "RenamedAgain"})
    audit.refresh_from_db()
    assert audit.user_id == user.pk and audit.changes["username"]["new"] == "Renamed"


def test_player_names_rolls_back_when_audit_fails(moderator, user, monkeypatch):
    monkeypatch.setattr(
        "moderation.workspace.Activity.objects.create",
        Mock(side_effect=RuntimeError("Audit unavailable")),
    )
    with pytest.raises(RuntimeError):
        change_names(moderator, user.pk, {"username": "Renamed"})
    user.refresh_from_db()
    assert user.username == "pixelplayer"


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_player_names_cannot_claim_same_username(moderator, user):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("File-backed SQLite required for concurrent writer checks")
    from threading import Barrier

    other = User.objects.create_user(username="otherplayer", email="other@example.test")
    barrier = Barrier(2)

    def rename(target_id):
        close_old_connections()
        try:
            actor = User.objects.get(pk=moderator.pk)
            barrier.wait(timeout=10)
            try:
                change_names(actor, target_id, {"username": "ClaimedName"})
                return True
            except ValidationError:
                return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(rename, [user.pk, other.pk]))
    assert sorted(results) == [False, True]
    assert User.objects.filter(username__iexact="ClaimedName").count() == 1
    assert Activity.objects.filter(action="player_names_changed").count() == 1


@pytest.mark.parametrize("collision", [False, True])
def test_player_names_refreshes_live_party_alias_only(
    moderator, user, collision, django_capture_on_commit_callbacks
):
    from games.models import Party, PartyMember

    now = timezone.now()
    live = Party.objects.create(
        code="NAMES1", create_request_id=uuid.uuid4(), expires_at=now + timedelta(days=1)
    )
    historical = Party.objects.create(
        code="NAMES2",
        create_request_id=uuid.uuid4(),
        expires_at=now + timedelta(days=1),
        status="closed",
    )
    member = PartyMember.objects.create(
        party=live, user=user, display_name=user.username, name_key=user.username, last_seen=now
    )
    past = PartyMember.objects.create(
        party=historical,
        user=user,
        display_name=user.username,
        name_key=user.username,
        last_seen=now,
    )
    if collision:
        PartyMember.objects.create(
            party=live,
            user=moderator,
            display_name="Fresh name",
            name_key="fresh name",
            last_seen=now,
        )
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        change_names(moderator, user.pk, {"display_name": "Fresh name"})
    member.refresh_from_db()
    past.refresh_from_db()
    assert member.display_name == ("Fresh name (2)" if collision else "Fresh name")
    assert member.user_id == past.user_id == user.pk and past.display_name == "pixelplayer"
    assert len(callbacks) == 2  # Party invalidation and account-session invalidation.


def sanction(moderator, user, kind="warning", **kwargs):
    return issue(moderator, user.pk, {"kind": kind, "category": "fair_play", **kwargs})


@pytest.mark.parametrize("path", ["", "players/", "reports/", "appeals/"])
def test_workspace_denies_guests_and_players(client, user, path):
    assert client.get(ROOT + path).status_code == 403
    authenticate(client, user)
    assert client.get(ROOT + path).status_code == 403


def test_native_role_has_no_admin_access(client, moderator, administrator):
    authenticate(client, moderator)
    assert client.get(ROOT).status_code == 200
    client.force_authenticate(None)
    client.force_login(moderator)
    assert client.get("/admin/").status_code == 302
    moderator.is_staff = True
    moderator.save()
    assert client.get("/admin/moderation/sanction/").status_code == 302
    client.force_login(administrator)
    assert client.get("/admin/").status_code == 200


def test_legacy_staff_cannot_establish_admin_login_session(staff):
    client = APIClient()
    response = client.post(
        "/admin/login/?next=/admin/",
        {"username": staff.username, "password": "a-strong-staff-pass-734", "next": "/admin/"},
    )
    assert response.status_code == 200
    assert b"Administrator access is required" in response.content
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize("target", ["staff", "moderator", "administrator"])
def test_staff_protection_on_search_details_actions(
    client, user, staff, moderator, administrator, target
):
    protected = {"staff": staff, "moderator": moderator, "administrator": administrator}[target]
    if target == "administrator":
        protected = User.objects.create_superuser(
            username="other_admin", email="other@example.test"
        )
    authenticate(client, moderator)
    rows = client.get(ROOT + "players/").json()["results"]
    assert str(protected.pk) not in {row["id"] for row in rows}
    assert client.get(ROOT + f"players/{protected.pk}/").status_code == 404
    assert (
        client.post(
            ROOT + f"players/{protected.pk}/sanctions/", {"kind": "warning"}, format="json"
        ).status_code
        == 403
    )
    authenticate(client, administrator)
    assert (
        client.post(
            ROOT + f"players/{protected.pk}/sanctions/", {"kind": "warning"}, format="json"
        ).status_code
        == 201
    )


def test_inactive_native_moderator_remains_protected(client, moderator, user, administrator):
    from moderation.workspace import change_access

    change_access(administrator, user.pk, True)
    user.is_active = False
    user.save(update_fields=["is_active"])
    authenticate(client, moderator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/sanctions/", {"kind": "warning"}, format="json"
        ).status_code
        == 403
    )


def test_optional_reasons_internal_privacy_and_audit(client, user, moderator):
    authenticate(client, moderator)
    response = client.post(
        ROOT + f"players/{user.pk}/sanctions/",
        {"kind": "warning", "internal_note": "PRIVATE-STAFF-NOTE", "issued_by": str(user.pk)},
        format="json",
    )
    assert response.status_code == 201
    warning = Sanction.objects.get(pk=response.json()["id"])
    assert warning.issued_by_id == moderator.pk and warning.reason == ""
    audit = Activity.objects.get(sanction=warning)
    assert audit.actor_id == moderator.pk and audit.user_id == user.pk
    authenticate(client, user)
    for path in [
        "/api/moderation/sanctions/",
        "/api/moderation/notices/",
        "/api/auth/me/",
        f"/api/auth/profiles/{user.username}/",
    ]:
        body = client.get(path).content.decode()
        assert "PRIVATE-STAFF-NOTE" not in body and "internal_note" not in body
    assert client.get("/api/moderation/notices/").json()["sanctions"][0]["reason"]


@pytest.mark.parametrize("kind", ["probation", "suspension", "closed"])
def test_active_limits_and_coexistence(moderator, user, kind):
    sanction(moderator, user, kind)
    with pytest.raises(ValidationError):
        sanction(moderator, user, kind)
    sanction(moderator, user, "warning")
    sanction(moderator, user, "warning")
    assert user.sanctions.count() == 3


def test_distinct_types_coexist_and_restrictions_preserved(moderator, user):
    for kind in Sanction.Kind.values:
        sanction(moderator, user, kind)
    assert account_restrictions(user)["blocked"] and account_restrictions(user)["probation"]


def test_expired_type_does_not_block_new_sanction(moderator, user):
    prior = sanction(moderator, user, "probation")
    Sanction.objects.filter(pk=prior.pk).update(
        starts_at=timezone.now() - timedelta(days=2), expires_at=timezone.now() - timedelta(days=1)
    )
    sanction(moderator, user, "probation")
    assert user.sanctions.count() == 2


def test_closure_changes_require_administrator_reopen(client, moderator, administrator, user):
    closed = sanction(moderator, user, "closed", reason="Original public closure reason")
    probation = sanction(moderator, user, "probation")
    before = Activity.objects.count()
    for actor, expected in [(moderator, 403), (administrator, 400)]:
        authenticate(client, actor)
        for action in ["reverse", "replace"]:
            response = client.post(
                ROOT + f"sanctions/{closed.pk}/{action}/", {"kind": "warning"}, format="json"
            )
            assert response.status_code == expected
            if actor == administrator:
                assert "Administrator Controls" in response.json()["detail"]
    closed.refresh_from_db()
    assert not closed.revoked_at and closed.reason == "Original public closure reason"
    assert user.sanctions.count() == 2 and Activity.objects.count() == before
    assert account_restrictions(user)["blocked"]
    authenticate(client, administrator)
    assert (
        client.post(
            ROOT + f"administration/players/{user.pk}/",
            {"operation": "reopen", "reason": "Reviewed closure evidence"},
            format="json",
        ).status_code
        == 200
    )
    closed.refresh_from_db()
    probation.refresh_from_db()
    assert closed.revoked_at and closed.revoked_by_id == administrator.pk
    assert closed.reason == "Original public closure reason" and not probation.revoked_at
    assert (
        Activity.objects.get(user=user, action="admin_reopen").reason == "Reviewed closure evidence"
    )
    assert Activity.objects.filter(sanction=closed, action="sanction_reversed").count() == 1
    assert not account_restrictions(user)["blocked"]
    rows = client.get(ROOT + f"players/{user.pk}/").json()["sanctions"]
    assert any(row["id"] == str(closed.pk) and row["reason"] == closed.reason for row in rows)


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension"])
@pytest.mark.parametrize("action", ["replace", "reverse"])
@pytest.mark.parametrize("administrator_actor", [False, True])
def test_ordinary_sanction_actions_remain_available(
    client, moderator, administrator, user, kind, action, administrator_actor
):
    original = sanction(moderator, user, kind)
    actor = administrator if administrator_actor else moderator
    authenticate(client, actor)
    response = client.post(
        ROOT + f"sanctions/{original.pk}/{action}/",
        {"kind": kind, "category": "fair_play", "reason": "Updated reason"},
        format="json",
    )
    assert response.status_code == (201 if action == "replace" else 200)
    original.refresh_from_db()
    assert original.revoked_at and original.revoked_by_id == actor.pk
    if action == "replace":
        assert Sanction.objects.get(pk=response.json()["id"]).replaces_id == original.pk


def test_replace_is_linked_and_marks_appeal_changed(moderator, user):
    original = sanction(moderator, user, "probation", reason="Original")
    appeal = submit_appeal(user, original.pk, "Please reconsider.")
    replacement = issue(
        moderator,
        user.pk,
        {"kind": "probation", "category": "integrity", "reason": "Updated"},
        replacing=original.pk,
    )
    original.refresh_from_db()
    appeal.refresh_from_db()
    assert (
        original.reason == "Original"
        and original.revoked_at
        and replacement.replaces_id == original.pk
    )
    assert appeal.status == "sanction_changed" and appeal.resolved_by_id == moderator.pk
    assert eligibility(user, replacement)[
        "eligible"
    ]  # Changed pending appeals never start cooldowns.
    assert Activity.objects.filter(user=user).count() == 5


def test_replacement_rolls_back_original_appeal_and_activity(moderator, user):
    original = sanction(moderator, user, "probation")
    appeal = submit_appeal(user, original.pk, "Please reconsider.")
    count = Activity.objects.count()
    with pytest.raises(ValidationError):
        issue(
            moderator,
            user.pk,
            {
                "kind": "closed",
                "category": "fair_play",
                "expires_at": timezone.now() + timedelta(days=1),
            },
            replacing=original.pk,
        )
    original.refresh_from_db()
    appeal.refresh_from_db()
    assert original.revoked_at is None and appeal.status == "pending"
    assert Activity.objects.count() == count and Sanction.objects.count() == 1


@pytest.mark.parametrize("action", ["issue", "reverse"])
def test_audit_failure_rolls_back_mutation(moderator, user, monkeypatch, action):
    original = sanction(moderator, user) if action == "reverse" else None
    before = Sanction.objects.count()

    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(Activity.objects, "create", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        if original:
            reverse(moderator, original.pk)
        else:
            sanction(moderator, user)
    assert Sanction.objects.count() == before
    if original:
        original.refresh_from_db()
        assert original.revoked_at is None


def test_warning_appeal_one_per_record_and_no_second_after_review(moderator, user):
    first = sanction(moderator, user)
    appeal = submit_appeal(user, first.pk, "Please review.")
    review_appeal(moderator, appeal.pk, "uphold", confirm_own_uphold=True)
    with pytest.raises(ValidationError):
        submit_appeal(user, first.pk, "Again.")
    second = sanction(moderator, user)
    assert submit_appeal(user, second.pk, "Different warning.")
    reverse(moderator, first.pk)  # Upholding does not block independent reversal.


@pytest.mark.parametrize("kind,days", [("probation", 30), ("suspension", 90)])
def test_cooldown_starts_at_upheld_decision_and_survives_replacement(
    moderator, user, client, monkeypatch, kind, days
):
    clock = {"now": timezone.now() + timedelta(seconds=1)}
    monkeypatch.setattr(timezone, "now", lambda: clock["now"])
    original = sanction(moderator, user, kind)
    assert eligibility(user, original) == {
        "eligible": True,
        "detail": "You can appeal this sanction.",
        "available_at": None,
    }
    appeal = submit_appeal(user, original.pk, "Please review.")
    # An old pending submission has no cooldown date, even after more than 30/90 days.
    clock["now"] += timedelta(days=days + 7)
    assert eligibility(user, original)["available_at"] is None
    assert "pending" in eligibility(user, original)["detail"]
    with pytest.raises(ValidationError, match="pending"):
        submit_appeal(user, original.pk, "Duplicate.")
    review_appeal(moderator, appeal.pk, "uphold", confirm_own_uphold=True)
    appeal.refresh_from_db()
    assert appeal.resolved_at == clock["now"]
    deadline = appeal.resolved_at + timedelta(days=days)
    allowed = eligibility(user, original)
    assert not allowed["eligible"] and allowed["available_at"] == deadline.isoformat()
    authenticate(client, user)
    row = client.get("/api/moderation/notices/").json()["sanctions"][0]
    assert row["appeal"] == allowed
    replacement = issue(
        moderator, user.pk, {"kind": kind, "category": "fair_play"}, replacing=original.pk
    )
    assert eligibility(user, replacement)["available_at"] == deadline.isoformat()
    clock["now"] = deadline - timedelta(microseconds=1)
    with pytest.raises(ValidationError, match="cooldown"):
        submit_appeal(user, replacement.pk, "Too early.")
    clock["now"] = deadline
    assert submit_appeal(user, replacement.pk, "Cooldown ended.")
    assert eligibility(user, replacement)["available_at"] is None


@pytest.mark.parametrize("kind", ["probation", "suspension"])
def test_approved_and_changed_appeals_do_not_start_cooldown(moderator, user, kind):
    original = sanction(moderator, user, kind)
    appeal = submit_appeal(user, original.pk, "Please review.")
    review_appeal(moderator, appeal.pk, "reverse")
    appeal.refresh_from_db()
    assert appeal.status == "reversed" and appeal.resolved_at
    replacement = sanction(moderator, user, kind)
    assert eligibility(user, replacement)["eligible"]
    pending = submit_appeal(user, replacement.pk, "Please review again.")
    newest = issue(
        moderator, user.pk, {"kind": kind, "category": "fair_play"}, replacing=replacement.pk
    )
    pending.refresh_from_db()
    assert pending.status == "sanction_changed"
    assert eligibility(user, newest)["eligible"]
    assert eligibility(user, newest)["available_at"] is None


@pytest.mark.parametrize("kind,days", [("probation", 30), ("suspension", 90)])
def test_latest_upheld_decision_controls_only_its_sanction_type(moderator, user, kind, days):
    notice = sanction(moderator, user, kind)
    now = timezone.now()
    # Decision chronology, not submission chronology, determines the cooldown.
    for submitted, decided in [(20, 2), (10, 5)]:
        Appeal.objects.create(
            user=user,
            sanction=notice,
            kind=kind,
            explanation="Historical decision.",
            status="upheld",
            created_at=now - timedelta(days=submitted),
            resolved_at=now - timedelta(days=decided),
            resolved_by=moderator,
        )
    other = sanction(moderator, user, "suspension" if kind == "probation" else "probation")
    other_appeal = submit_appeal(user, other.pk, "Different type.")
    review_appeal(moderator, other_appeal.pk, "uphold", confirm_own_uphold=True)
    assert eligibility(user, notice)["available_at"] == (now + timedelta(days=days - 2)).isoformat()


def test_appeal_resolution_reverses_and_prevents_double_review(moderator, user):
    warning = sanction(moderator, user)
    appeal = submit_appeal(user, warning.pk, "Please review.")
    result = review_appeal(moderator, appeal.pk, "reverse")
    warning.refresh_from_db()
    assert result.status == "reversed" and warning.revoked_at
    with pytest.raises(ValidationError):
        review_appeal(moderator, appeal.pk, "uphold")


@pytest.mark.parametrize("state", ["closed", "expired", "reversed"])
def test_ineligible_sanctions_reject_appeals(moderator, user, state):
    notice = sanction(moderator, user, "closed" if state == "closed" else "warning")
    if state == "expired":
        Sanction.objects.filter(pk=notice.pk).update(
            starts_at=timezone.now() - timedelta(days=100),
            expires_at=timezone.now() - timedelta(days=10),
        )
    if state == "reversed":
        reverse(moderator, notice.pk)
    with pytest.raises(ValidationError):
        submit_appeal(user, notice.pk, "Please review.")


def test_report_inbox_resolution_privacy_and_staff_exclusion(
    client, moderator, administrator, user
):
    reporter = User.objects.create_user(username="reporter", email="reporter@example.test")
    report = Report.objects.create(
        reporter=reporter, subject=user, category="fair_play", details="Review this."
    )
    staff_report = Report.objects.create(
        reporter=user, subject=moderator, category="fair_play", details="Private staff target"
    )
    authenticate(client, moderator)
    rows = client.get(ROOT + "reports/").json()["results"]
    assert [r["id"] for r in rows] == [str(report.pk)]
    assert (
        client.post(
            ROOT + f"reports/{staff_report.pk}/resolve/", {"decision": "resolved"}, format="json"
        ).status_code
        == 403
    )
    assert (
        client.post(
            ROOT + f"reports/{report.pk}/resolve/", {"decision": "dismissed"}, format="json"
        ).status_code
        == 200
    )
    assert Activity.objects.get(report=report).actor_id == moderator.pk
    authenticate(client, user)
    assert client.get(ROOT + "reports/").status_code == 403


def test_role_management_and_immediate_revocation(client, moderator, administrator, user):
    authenticate(client, moderator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/access/", {"enabled": True}, format="json"
        ).status_code
        == 403
    )
    authenticate(client, administrator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/access/", {"enabled": True}, format="json"
        ).status_code
        == 200
    )
    user.refresh_from_db()
    assert not user.is_staff
    authenticate(client, user)
    assert client.get(ROOT).status_code == 200
    change_access(administrator, user.pk, False)
    # Real session authentication reloads permissions; service checks also ignore stale actor cache.
    with pytest.raises(PermissionDenied) as exc:
        sanction(user, moderator)
    assert "Moderator access" in str(exc.value)
    authenticate(client, User.objects.get(pk=user.pk))
    assert client.get(ROOT).status_code == 403


def test_suspended_normal_login_and_authenticated_appeals(user, moderator):
    suspension = sanction(moderator, user, "suspension", internal_note="SECRET")
    client = APIClient(enforce_csrf_checks=True)
    credentials = {"username": user.username, "password": "a-strong-unique-pass-734"}
    assert (
        client.post("/api/moderation/notice-login/", credentials, format="json").status_code == 404
    )

    def csrf():
        return {"HTTP_X_CSRFTOKEN": client.get("/api/auth/csrf/").json()["csrfToken"]}

    assert client.post("/api/auth/login/", credentials, format="json", **csrf()).status_code == 200
    assert client.get("/api/auth/me/").json()["user"]["id"] == str(user.pk)
    assert client.get("/api/auth/settings/").status_code == 200
    notices = client.get("/api/moderation/notices/")
    assert notices.status_code == 200 and b"SECRET" not in notices.content
    assert client.get(ROOT).status_code == 403
    assert (
        client.post(
            "/api/ranked/queue/",
            {"request_id": str(uuid.uuid4())},
            format="json",
            **csrf(),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/moderation/sanctions/{suspension.pk}/appeal/",
            {"explanation": "Please review."},
            format="json",
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/moderation/sanctions/{suspension.pk}/appeal/",
            {"explanation": "Please review."},
            format="json",
            **csrf(),
        ).status_code
        == 201
    )
    assert "notice_access" not in client.session


def test_foreign_appeal_empty_explanation_and_csrf(client, moderator, user):
    other = User.objects.create_user(username="other", email="other@example.test")
    foreign = sanction(moderator, other)
    warning = sanction(moderator, user)
    authenticate(client, user)
    assert (
        client.post(
            f"/api/moderation/sanctions/{foreign.pk}/appeal/",
            {"explanation": "Review"},
            format="json",
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/moderation/sanctions/{warning.pk}/appeal/", {"explanation": "   "}, format="json"
        ).status_code
        == 400
    )
    real = APIClient(enforce_csrf_checks=True)
    real.force_login(moderator)
    assert (
        real.post(
            ROOT + f"players/{user.pk}/sanctions/", {"kind": "warning"}, format="json"
        ).status_code
        == 403
    )


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("action", ["issue", "appeal", "replace", "reverse", "review"])
def test_concurrent_workspace_decisions(moderator, user, action):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("File-backed SQLite required for concurrent writer checks")
    original = sanction(moderator, user, "probation") if action != "issue" else None
    pending_appeal = (
        submit_appeal(user, original.pk, "Review this.") if action == "review" else None
    )

    def run(_):
        close_old_connections()
        try:
            actor = User.objects.get(pk=moderator.pk)
            target = User.objects.get(pk=user.pk)
            if action == "issue":
                sanction(actor, target, "probation")
            elif action == "appeal":
                submit_appeal(target, original.pk, "Concurrent review")
            elif action == "reverse":
                reverse(actor, original.pk)
            elif action == "review":
                review_appeal(actor, pending_appeal.pk, "reverse")
            else:
                issue(
                    actor,
                    target.pk,
                    {"kind": "probation", "category": "fair_play"},
                    replacing=original.pk,
                )
            return True
        except (ValidationError, ModelValidationError):
            return False
        except Exception as exc:
            from django.http import Http404

            if isinstance(exc, Http404):
                return False
            raise
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run, range(2)))
    assert sorted(results) == [False, True]
    if action == "appeal":
        assert Appeal.objects.count() == 1
    elif action in ["issue", "replace"]:
        assert user.sanctions.filter(revoked_at__isnull=True).count() == 1
    else:
        assert user.sanctions.filter(revoked_at__isnull=True).count() == 0


@pytest.mark.parametrize("kind", ["probation", "suspension"])
def test_api_supports_indefinite_and_fixed_duration_replacements(client, moderator, user, kind):
    authenticate(client, moderator)
    response = client.post(
        ROOT + f"players/{user.pk}/sanctions/", {"kind": kind, "expires_at": None}, format="json"
    )
    assert response.status_code == 201 and response.json()["expires_at"] is None
    original = response.json()["id"]
    fixed = timezone.now() + timedelta(days=2)
    response = client.post(
        ROOT + f"sanctions/{original}/replace/",
        {"kind": kind, "expires_at": fixed.isoformat()},
        format="json",
    )
    assert response.status_code == 201
    fixed_id = response.json()["id"]
    assert Sanction.objects.get(pk=fixed_id).expires_at == fixed
    response = client.post(
        ROOT + f"sanctions/{fixed_id}/replace/", {"kind": kind, "expires_at": None}, format="json"
    )
    assert response.status_code == 201 and response.json()["expires_at"] is None
    authenticate(client, user)
    notices = client.get("/api/moderation/notices/").json()["sanctions"]
    assert len(notices) == 3
    active = next(row for row in notices if row["active"])
    assert active["expires_at"] is None and active["appeal"]["eligible"]
    assert Activity.objects.filter(user=user, action="sanction_replaced").count() == 2


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension", "closed"])
@pytest.mark.parametrize("role", ["moderator", "administrator"])
def test_staff_cannot_sanction_themselves_through_api(client, moderator, administrator, role, kind):
    actor = {"moderator": moderator, "administrator": administrator}[role]
    authenticate(client, actor)
    response = client.post(ROOT + f"players/{actor.pk}/sanctions/", {"kind": kind}, format="json")
    assert response.status_code == 403
    assert "own account" in response.json()["detail"]
    assert not Sanction.objects.exists() and not Activity.objects.exists()
    actor.refresh_from_db()
    assert actor.is_active


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension", "closed"])
@pytest.mark.parametrize("role", ["moderator", "administrator"])
def test_shared_model_and_admin_creation_reject_self_sanctions(
    moderator, administrator, role, kind
):
    from django.contrib import admin
    from django.test import RequestFactory

    actor = {"moderator": moderator, "administrator": administrator}[role]
    data = {"user": actor, "issued_by": actor, "kind": kind, "category": "fair_play"}
    with pytest.raises(ModelValidationError, match="own account"):
        Sanction.objects.create(**data)
    request = RequestFactory().post("/admin/moderation/sanction/add/")
    request.user = actor
    with pytest.raises(ModelValidationError, match="own account"):
        admin.site._registry[Sanction].save_model(request, Sanction(**data), None, False)
    assert not Sanction.objects.exists() and not Activity.objects.exists()


@pytest.mark.parametrize("role", ["moderator", "administrator"])
def test_self_replacement_is_denied_without_reversing_original(
    client, moderator, administrator, role
):
    actor = {"moderator": moderator, "administrator": administrator}[role]
    other = User.objects.create_superuser(username="second_admin", email="second@example.test")
    original = issue(other, actor.pk, {"kind": "warning", "category": "fair_play"})
    before = Activity.objects.count()
    authenticate(client, actor)
    result = client.post(
        ROOT + f"sanctions/{original.pk}/replace/", {"kind": "suspension"}, format="json"
    )
    assert result.status_code == 403
    original.refresh_from_db()
    assert original.revoked_at is None
    assert Sanction.objects.count() == 1 and Activity.objects.count() == before


@pytest.mark.parametrize("target_role", ["moderator", "administrator", "legacy_staff"])
def test_model_imposition_preserves_staff_protection(moderator, administrator, staff, target_role):
    other_mod = User.objects.create_user(username="another_mod", email="another@example.test")
    change_access(administrator, other_mod.pk, True)
    target = {"moderator": other_mod, "administrator": administrator, "legacy_staff": staff}[
        target_role
    ]
    with pytest.raises(ModelValidationError, match="protected staff"):
        Sanction.objects.create(
            user=target, issued_by=moderator, kind="warning", category="fair_play"
        )
    assert not Sanction.objects.exists()
    if target.pk == administrator.pk:
        issuer = User.objects.create_superuser(username="second_admin", email="second@example.test")
    else:
        issuer = administrator
    assert (
        issue(issuer, target.pk, {"kind": "warning", "category": "fair_play"}).user_id == target.pk
    )


@pytest.mark.parametrize("target_self", [True, False])
@pytest.mark.parametrize("api_kind", ["native", "administration"])
def test_administrator_access_cannot_be_removed_by_any_moderator_control(
    client, administrator, target_self, api_kind
):
    from moderation.administration import manage_player

    target = (
        administrator
        if target_self
        else User.objects.create_superuser(username="second_admin", email="second@example.test")
    )
    permission = Permission.objects.get(
        content_type__app_label="moderation", codename="access_workspace"
    )
    target.user_permissions.add(permission)
    before = (
        target.is_staff,
        target.is_superuser,
        set(target.user_permissions.values_list("pk", flat=True)),
    )
    authenticate(client, administrator)
    url = (
        ROOT + f"players/{target.pk}/access/"
        if api_kind == "native"
        else ROOT + f"administration/players/{target.pk}/"
    )
    body = (
        {"enabled": False} if api_kind == "native" else {"operation": "moderator", "enabled": False}
    )
    assert client.post(url, body, format="json").status_code == 400
    with pytest.raises(ValidationError, match="command-line-only"):
        change_access(administrator, target.pk, False)
    with pytest.raises(ValidationError, match="command-line-only"):
        manage_player(administrator, target.pk, "moderator", {"enabled": False})
    target.refresh_from_db()
    assert before == (
        target.is_staff,
        target.is_superuser,
        set(target.user_permissions.values_list("pk", flat=True)),
    )
    assert not Activity.objects.exists()
    summary = client.get(ROOT + f"players/{target.pk}/").json()["player"]
    assert summary["moderator"] and summary["can_remove_moderator"] is False


def test_native_moderator_removal_eligibility_and_admin_self_name_edit(
    client, administrator, moderator
):
    authenticate(client, administrator)
    summary = client.get(ROOT + f"players/{moderator.pk}/").json()["player"]
    assert summary["can_remove_moderator"] is True
    updated = change_names(administrator, administrator.pk, {"display_name": "My display name"})
    assert updated.display_name == "My display name"


def test_admin_sanction_form_excludes_self(administrator, user):
    from django.contrib import admin
    from django.test import RequestFactory

    request = RequestFactory().get("/admin/moderation/sanction/add/")
    request.user = administrator
    form = admin.site._registry[Sanction].get_form(request)()
    assert not form.fields["user"].queryset.filter(pk=administrator.pk).exists()
    assert form.fields["user"].queryset.filter(pk=user.pk).exists()


def test_legacy_self_warning_can_be_acknowledged_but_not_reimposed(client, administrator, user):
    original = issue(administrator, user.pk, {"kind": "warning", "category": "fair_play"})
    # Represent pre-existing history without creating a new self-sanction via normal paths.
    Sanction.objects.filter(pk=original.pk).update(issued_by=user)
    authenticate(client, user)
    assert client.post(f"/api/moderation/sanctions/{original.pk}/acknowledge/").status_code == 200
    original.refresh_from_db()
    assert original.acknowledged_at is not None
    original.kind = "probation"
    with pytest.raises(ModelValidationError, match="own account"):
        original.save()
