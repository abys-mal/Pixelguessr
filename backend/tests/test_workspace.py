import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

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


def test_closure_reverse_and_replace_administrator_only(client, moderator, administrator, user):
    closed = sanction(moderator, user, "closed")
    authenticate(client, moderator)
    for action in ["reverse", "replace"]:
        assert (
            client.post(
                ROOT + f"sanctions/{closed.pk}/{action}/", {"kind": "warning"}, format="json"
            ).status_code
            == 403
        )
    closed.refresh_from_db()
    assert not closed.revoked_at
    authenticate(client, administrator)
    assert client.post(ROOT + f"sanctions/{closed.pk}/reverse/").status_code == 200
    assert not account_restrictions(user)["blocked"]


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
    review_appeal(moderator, appeal.pk, "uphold")
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
    review_appeal(moderator, appeal.pk, "uphold")
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
    review_appeal(moderator, other_appeal.pk, "uphold")
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
