import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.db import close_old_connections, connection
from django.utils import timezone
from rest_framework.test import APIClient
from test_admin_audit import grant, notice, request_for

from accounts.models import User
from games.models import Match, Participant
from moderation.models import Report, Sanction
from moderation.services import account_restrictions

pytestmark = pytest.mark.django_db
BASE = "/api/moderation/"


def report_body(account, **extra):
    return {
        "subject": str(account.pk),
        "category": "fair_play",
        "details": "Observed a suspicious round.",
        **extra,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"subject": "bad-uuid"},
        {"category": "invalid"},
        {"details": ""},
        {"details": " "},
        {"details": "x" * 2001},
        {"subject": str(uuid.uuid4())},
    ],
)
def test_report_invalid_inputs_rejected_without_storage(client, user, staff, bad):
    client.force_authenticate(user)
    assert (
        client.post(BASE + "reports/", report_body(staff, **bad), format="json").status_code == 400
    )
    assert not Report.objects.exists()


@pytest.mark.parametrize("missing", ["subject", "category", "details"])
def test_report_required_fields(client, user, staff, missing):
    body = report_body(staff)
    body.pop(missing)
    client.force_authenticate(user)
    response = client.post(BASE + "reports/", body, format="json")
    assert response.status_code == 400 and missing in response.json()


def test_report_duplicate_policy_rate_limit_and_server_owned_fields(client, user, staff):
    client.force_authenticate(user)
    for _ in range(10):
        response = client.post(
            BASE + "reports/",
            report_body(
                staff,
                reporter=str(staff.pk),
                resolved_at=timezone.now().isoformat(),
                id=str(uuid.uuid4()),
            ),
            format="json",
        )
        assert response.status_code == 201
    assert client.post(BASE + "reports/", report_body(staff), format="json").status_code == 429
    assert Report.objects.count() == 10  # Existing policy permits separate reports up to the limit.
    assert not Report.objects.exclude(reporter=user).exists()
    assert not Report.objects.filter(resolved_at__isnull=False).exists()
    entry = Report.objects.first()
    client.force_authenticate(staff)
    assert client.get(BASE + "reports/").status_code == 405
    assert (
        client.patch(
            BASE + f"reports/{entry.pk}/",
            {"resolved_at": timezone.now().isoformat()},
            format="json",
        ).status_code
        == 404
    )


def test_reports_require_authentication_and_real_session_csrf(user, staff):
    client = APIClient(enforce_csrf_checks=True)
    assert client.post(BASE + "reports/", report_body(staff), format="json").status_code == 403
    client.force_login(user)
    assert client.post(BASE + "reports/", report_body(staff), format="json").status_code == 403
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert (
        client.post(
            BASE + "reports/", report_body(staff), format="json", HTTP_X_CSRFTOKEN=token
        ).status_code
        == 201
    )


@pytest.mark.parametrize("kind", ["warning", "suspension", "closed"])
def test_restricted_users_cannot_submit_reports(client, user, staff, kind):
    notice(user, staff, kind)
    client.force_authenticate(user)
    assert client.post(BASE + "reports/", report_body(staff), format="json").status_code == 403
    assert not Report.objects.exists()


def test_report_admin_permissions_resolution_and_audit(client, user, staff):
    report = Report.objects.create(
        reporter=user, subject=staff, category="fair_play", details="Test report"
    )
    client.force_login(user)
    assert client.get(f"/admin/moderation/report/{report.pk}/change/").status_code == 302
    staff = grant(staff, "moderation.view_report")
    client.force_login(staff)
    assert client.get(f"/admin/moderation/report/{report.pk}/change/").status_code == 302
    assert (
        client.post(f"/admin/moderation/report/{report.pk}/change/", {"_save": "Save"}).status_code
        == 302
    )
    staff = grant(staff, "moderation.change_report")
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    client.force_login(staff)
    now = timezone.now()
    response = client.post(
        f"/admin/moderation/report/{report.pk}/change/",
        {
            "resolved_at_0": now.strftime("%Y-%m-%d"),
            "resolved_at_1": now.strftime("%H:%M:%S"),
            "subject": str(user.pk),
            "reporter": str(staff.pk),
            "details": "Tampered",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    report.refresh_from_db()
    assert (
        report.resolved_at is not None
        and report.subject_id == staff.pk
        and report.reporter_id == user.pk
    )
    assert report.details == "Test report"
    log = LogEntry.objects.get(object_id=str(report.pk))
    assert log.user_id == staff.pk and log.action_time is not None
    assert client.get("/admin/admin/logentry/").status_code == 404


@pytest.mark.parametrize("offset, active", [(89, True), (90, False), (91, False)])
def test_warning_exact_expiration_boundary(user, staff, monkeypatch, offset, active):
    now = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: now)
    warning = Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind="warning",
        category="fair_play",
        reason="Boundary",
        starts_at=now - timedelta(days=offset),
    )
    assert warning.expires_at == warning.starts_at + timedelta(days=90)
    assert bool(account_restrictions(user)["unacknowledged_warnings"]) is active


def test_scheduled_expired_and_revoked_sanctions(client, user, staff, monkeypatch):
    now = timezone.now()
    clock = {"now": now}
    monkeypatch.setattr(timezone, "now", lambda: clock["now"])
    suspension = Sanction.objects.create(
        user=user,
        issued_by=staff,
        kind="suspension",
        category="fair_play",
        reason="Temporary",
        starts_at=now + timedelta(hours=1),
        expires_at=now + timedelta(hours=2),
    )
    assert not account_restrictions(user)["blocked"]
    clock["now"] += timedelta(hours=1)
    assert account_restrictions(user)["blocked"]
    assert (
        client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "a-strong-unique-pass-734"},
            format="json",
        ).status_code
        == 400
    )
    clock["now"] += timedelta(hours=1)
    assert not account_restrictions(user)["blocked"]
    assert (
        client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "a-strong-unique-pass-734"},
            format="json",
        ).status_code
        == 200
    )
    assert Sanction.objects.get(pk=suspension.pk).issued_by_id == staff.pk


def test_closure_revoke_batch_is_atomic_and_admin_only(client, user, staff):
    staff = grant(staff, "moderation.change_sanction", "moderation.view_sanction")
    closed = notice(user, staff, "closed")
    warning = notice(user, staff)
    client.force_login(staff)
    response = client.post(
        "/admin/moderation/sanction/",
        {"action": "revoke", "index": "0", "_selected_action": [str(warning.pk), str(closed.pk)]},
    )
    assert response.status_code == 302  # Staff can only use the native workspace.
    assert not Sanction.objects.filter(revoked_at__isnull=False).exists()
    # Neither setting is_active nor a direct acknowledgment reopens a closure.
    user.is_active = True
    user.save()
    assert account_restrictions(user)["blocked"]
    client.force_authenticate(user)
    assert client.post(BASE + f"sanctions/{closed.pk}/acknowledge/").status_code == 404
    client.force_authenticate(None)
    staff.is_superuser = True
    staff.save()
    client.force_login(staff)
    assert (
        client.post(
            "/admin/moderation/sanction/",
            {"action": "revoke", "index": "0", "_selected_action": str(closed.pk)},
        ).status_code
        == 302
    )
    assert not account_restrictions(user)["blocked"]
    assert Sanction.objects.count() == 2


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_ordinary_users_cannot_modify_or_delete_sanction_audit(client, user, staff, method):
    warning = notice(user, staff)
    client.force_authenticate(user)
    response = getattr(client, method)(
        BASE + f"sanctions/{warning.pk}/acknowledge/",
        {"issued_by": str(user.pk), "reason": "Tampered"},
        format="json",
    )
    assert response.status_code == 405
    warning.refresh_from_db()
    assert warning.issued_by_id == staff.pk and warning.reason == "Audit test"
    assert not admin.site._registry[Sanction].has_delete_permission(request_for(staff), warning)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("action", ["acknowledge", "revoke"])
def test_concurrent_moderation_actions_preserve_first_timestamp_and_actor(user, staff, action):
    if connection.vendor == "sqlite" and connection.is_in_memory_db():
        pytest.skip("Use TEST_SQLITE_FILE for SQLite writer concurrency")
    warning = notice(user, staff)
    staff = grant(staff, "moderation.change_sanction")
    second = User.objects.create_user(
        username="secondmoderator", email="secondmoderator@example.test", is_staff=True
    )
    second = grant(second, "moderation.change_sanction")
    barrier = Barrier(2)

    def run(actor):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if action == "acknowledge":
                client = APIClient()
                client.force_authenticate(user)
                response = client.post(BASE + f"sanctions/{warning.pk}/acknowledge/")
                assert response.status_code == 200
                return response.json()["acknowledged_at"]
            admin.site._registry[Sanction].revoke(
                request_for(actor), Sanction.objects.filter(pk=warning.pk)
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, [staff, second]))
    warning.refresh_from_db()
    if action == "acknowledge":
        assert (
            results[0] == results[1] == warning.acknowledged_at.isoformat().replace("+00:00", "Z")
        )
    else:
        assert warning.revoked_by_id in [staff.pk, second.pk]
        assert LogEntry.objects.filter(object_id=str(warning.pk)).count() == 1


@pytest.mark.parametrize("outcome", ["victory", "forfeit", "no_contest"])
def test_history_classifies_supported_outcomes_without_inventing_draws(
    client, user, staff, outcome
):
    match = Match.objects.create(
        mode="ranked", status="complete", ranked_outcome=outcome, completed_at=timezone.now()
    )
    winner = Participant.objects.create(
        match=match,
        user=user,
        rating_before=1000,
        rating_after=1000,
        rating_delta=0,
        decisive_wins=4,
    )
    loser = Participant.objects.create(
        match=match,
        user=staff,
        rating_before=1000,
        rating_after=1000,
        rating_delta=0,
        decisive_wins=2,
    )
    if outcome != "no_contest":
        match.ranked_winner = winner
        match.save()
    for player, expected in [(winner, "win"), (loser, "loss")]:
        row = client.get(f"/api/ranked/history/{player.user.username}/").json()["results"][0]
        assert row["outcome"] == ("no_contest" if outcome == "no_contest" else expected)
        assert row["forfeit"] is (outcome == "forfeit")
        assert row["score"] == player.decisive_wins and row["rating_delta"] == 0


def test_malicious_report_details_are_escaped_in_admin(client, user, staff):
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    report = Report.objects.create(
        reporter=user, subject=staff, category="fair_play", details="<script>alert(1)</script>"
    )
    staff = grant(staff, "moderation.view_report")
    client.force_login(staff)
    response = client.get(f"/admin/moderation/report/{report.pk}/change/")
    assert response.status_code == 200
    assert b"<script>alert(1)</script>" not in response.content
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.content


def test_invalid_sanction_expiry_returns_form_error_without_partial_storage(client, user, staff):
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    staff = grant(staff, "moderation.add_sanction")
    client.force_login(staff)
    now = timezone.now()
    response = client.post(
        "/admin/moderation/sanction/add/",
        {
            "user": str(user.pk),
            "kind": "probation",
            "category": "fair_play",
            "reason": "Invalid expiry test",
            "starts_at_0": now.strftime("%Y-%m-%d"),
            "starts_at_1": "12:00:00",
            "expires_at_0": now.strftime("%Y-%m-%d"),
            "expires_at_1": "11:00:00",
            "_save": "Save",
        },
    )
    assert response.status_code == 200 and response.context["adminform"].form.errors
    assert not Sanction.objects.exists()
