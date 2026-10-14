from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from library.models import ImageSubmission
from moderation.models import Sanction

pytestmark = pytest.mark.django_db


def grant(user, *names):
    for name in names:
        app, codename = name.split(".")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=codename)
        )
    return User.objects.get(pk=user.pk)


def notice(user, staff, kind="warning"):
    return Sanction.objects.create(
        user=user, issued_by=staff, kind=kind, category="fair_play", reason="Audit test"
    )


def request_for(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


@pytest.fixture
def administrator():
    return User.objects.create_superuser(
        username="auditadmin", email="admin@example.test", password="audit-test-password-951!"
    )


def test_view_only_staff_cannot_revoke_sanctions(client, user, staff):
    staff = grant(staff, "moderation.view_sanction")
    warning = notice(user, staff)
    model_admin = admin.site._registry[Sanction]
    assert "revoke" not in model_admin.get_actions(request_for(staff))
    client.force_login(staff)
    client.post(
        "/admin/moderation/sanction/",
        {"action": "revoke", "index": "0", "_selected_action": str(warning.pk)},
    )
    warning.refresh_from_db()
    assert warning.revoked_at is None


def test_view_only_image_reviewer_cannot_approve(user, staff, category):
    staff = grant(staff, "library.view_imagesubmission")
    image = ImageSubmission.objects.create(
        submitted_by=user,
        category=category,
        canonical_answer="Test",
        source="manual",
        external_image_url="https://example.test/image.png",
        license="CC0",
        attribution="Original",
    )
    model_admin = admin.site._registry[ImageSubmission]
    assert "approve" not in model_admin.get_actions(request_for(staff))
    with pytest.raises(PermissionDenied):
        model_admin.approve(request_for(staff), ImageSubmission.objects.filter(pk=image.pk))
    image.refresh_from_db()
    assert image.status == "pending"


def test_unchanged_sanction_admin_save_preserves_original_issuer(user, staff, administrator):
    warning = notice(user, staff)
    admin.site._registry[Sanction].save_model(request_for(administrator), warning, None, True)
    warning.refresh_from_db()
    assert warning.issued_by_id == staff.pk


def test_historical_staff_removal_does_not_break_warning_acknowledgment(client, user, staff):
    warning = notice(user, staff)
    staff.is_staff = False
    staff.save(update_fields=["is_staff"])
    client.force_authenticate(user)
    response = client.post(f"/api/moderation/sanctions/{warning.pk}/acknowledge/")
    assert response.status_code == 200
    warning.refresh_from_db()
    assert warning.acknowledged_at is not None and warning.issued_by_id == staff.pk


def test_moderator_cannot_promote_player_or_edit_privileged_accounts(
    client, user, staff, administrator
):
    staff = grant(staff, "accounts.view_user", "accounts.change_user", "accounts.delete_user")
    model_admin = admin.site._registry[User]
    request = request_for(staff)
    assert not model_admin.has_change_permission(request, administrator)
    assert not model_admin.has_delete_permission(request, administrator)
    assert not model_admin.has_change_permission(request, staff)
    form = model_admin.get_form(request, user)
    assert not {"is_staff", "is_superuser", "groups", "user_permissions"} & set(form.base_fields)
    client.force_login(staff)
    for path in [
        f"/admin/accounts/user/{administrator.pk}/change/",
        f"/admin/accounts/user/{administrator.pk}/password/",
    ]:
        assert (
            client.post(
                path,
                {
                    "is_superuser": "on",
                    "password1": "another-test-password",
                    "password2": "another-test-password",
                },
            ).status_code
            == 302
        )
    response = client.post(
        f"/admin/accounts/user/{user.pk}/change/",
        {
            "username": user.username,
            "email": user.email,
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
            "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
            "_save": "Save",
        },
    )
    assert response.status_code in [200, 302]
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser


def test_moderator_cannot_expand_group_permissions(client, staff):
    staff = grant(
        staff, "auth.view_group", "auth.change_group", "auth.add_group", "auth.delete_group"
    )
    group = Group.objects.create(name="Audit moderators")
    staff.groups.add(group)
    model_admin = admin.site._registry[Group]
    request = request_for(staff)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, group)
    assert not model_admin.has_delete_permission(request, group)
    client.force_login(staff)
    escalated = Permission.objects.get(content_type__app_label="accounts", codename="change_user")
    response = client.post(
        f"/admin/auth/group/{group.pk}/change/",
        {"name": group.name, "permissions": str(escalated.pk), "_save": "Save"},
    )
    assert response.status_code == 302  # Non-administrators cannot enter Django Admin.
    assert not group.permissions.exists()


def test_reports_cannot_be_created_in_admin_with_missing_readonly_identity(client, administrator):
    client.force_login(administrator)
    assert client.get("/admin/moderation/report/add/").status_code == 403


@pytest.mark.parametrize("state", ["guest", "expired", "suspended"])
def test_logout_is_idempotent_and_csrf_protected_for_stale_sessions(user, staff, state):
    client = APIClient(enforce_csrf_checks=True)
    key = None
    if state != "guest":
        client.force_login(user)
        key = client.session.session_key
    if state == "expired":
        Session.objects.filter(session_key=key).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
    elif state == "suspended":
        notice(user, staff, "suspension")
    assert client.post("/api/auth/logout/").status_code == 403
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert client.get("/api/auth/me/").json()["user"] is None
    if state == "suspended":
        assert not Session.objects.filter(session_key=key).exists()


def test_revoke_logs_actor_target_and_remains_idempotent(client, user, staff):
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    staff = grant(staff, "moderation.view_sanction", "moderation.change_sanction")
    warning = notice(user, staff)
    client.force_login(staff)
    body = {"action": "revoke", "index": "0", "_selected_action": str(warning.pk)}
    assert client.post("/admin/moderation/sanction/", body).status_code == 302
    warning.refresh_from_db()
    original = (warning.revoked_at, warning.revoked_by_id)
    assert original[1] == staff.pk
    entries = LogEntry.objects.filter(object_id=str(warning.pk), action_flag=CHANGE)
    assert entries.count() == 1 and entries.get().user_id == staff.pk
    assert str(user.pk) in entries.get().change_message
    client.post("/admin/moderation/sanction/", body)
    warning.refresh_from_db()
    assert (warning.revoked_at, warning.revoked_by_id) == original
    assert entries.count() == 1


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension", "closed"])
def test_admin_issues_sanction_with_server_owned_actor_and_addition_log(client, user, staff, kind):
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    staff = grant(staff, "moderation.add_sanction", "moderation.view_sanction")
    client.force_login(staff)
    now = timezone.now()
    response = client.post(
        "/admin/moderation/sanction/add/",
        {
            "user": str(user.pk),
            "issued_by": str(user.pk),
            "category": "fair_play",
            "kind": kind,
            "reason": "Admin workflow test",
            "starts_at_0": now.strftime("%Y-%m-%d"),
            "starts_at_1": now.strftime("%H:%M:%S"),
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    sanction = Sanction.objects.get(user=user)
    assert sanction.kind == kind and sanction.issued_by_id == staff.pk
    if kind == "warning":
        assert sanction.expires_at == sanction.starts_at + timedelta(days=90)
    if kind == "closed":
        assert sanction.expires_at is None
    assert LogEntry.objects.get(object_id=str(sanction.pk)).user_id == staff.pk


def test_revoke_keeps_historical_actors_valid_after_both_are_demoted(user, staff):
    warning = notice(user, staff)
    replacement = User.objects.create_user(
        username="replacement", email="replacement@example.test", is_staff=True
    )
    replacement = grant(replacement, "moderation.change_sanction")
    staff.is_staff = False
    staff.save(update_fields=["is_staff"])
    admin.site._registry[Sanction].revoke(
        request_for(replacement), Sanction.objects.filter(pk=warning.pk)
    )
    replacement.is_staff = False
    replacement.save(update_fields=["is_staff"])
    warning.refresh_from_db()
    warning.full_clean()
    assert warning.issued_by_id == staff.pk and warning.revoked_by_id == replacement.pk


@pytest.mark.parametrize("synonyms", [None, []])
def test_image_review_actions_record_admin_history(client, user, staff, category, synonyms):
    staff = grant(staff, "library.change_imagesubmission")
    client.force_authenticate(user)
    body = {
        "category": category.pk,
        "canonical_answer": "Test",
        "source": "manual",
        "external_image_url": "https://example.test/image.png",
        "license": "CC0",
        "attribution": "Original",
    }
    if synonyms is not None:
        body["accepted_synonyms"] = synonyms
    response = client.post("/api/library/submissions/", body, format="json")
    assert response.status_code == 201
    image = ImageSubmission.objects.get(pk=response.json()["id"])
    assert image.accepted_synonyms == [] and image.status == "pending"
    model_admin = admin.site._registry[ImageSubmission]
    for action, expected in [(model_admin.approve, "approved"), (model_admin.reject, "rejected")]:
        action(request_for(staff), ImageSubmission.objects.filter(pk=image.pk))
        image.refresh_from_db()
        assert image.status == expected and image.reviewed_by_id == staff.pk
    assert LogEntry.objects.filter(object_id=str(image.pk), user=staff).count() == 2


@pytest.mark.parametrize("operation", ["revoke", "replace"])
def test_cosmetic_title_preserves_or_renews_verification_provenance(
    user, staff, administrator, monkeypatch, operation
):
    from types import SimpleNamespace

    from accounts.models import VerifiedTitle

    title = VerifiedTitle.objects.create(user=user, title="pro", verified_by=staff)
    original = title.verified_at
    now = original + timedelta(hours=1)
    monkeypatch.setattr(timezone, "now", lambda: now)
    staff.is_staff = False
    staff.save(update_fields=["is_staff"])
    if operation == "revoke":
        title.revoked_at = now
        fields = ["revoked_at"]
    else:
        title.title = "master"
        fields = ["title"]
    admin.site._registry[VerifiedTitle].save_model(
        request_for(administrator), title, SimpleNamespace(changed_data=fields), True
    )
    title.refresh_from_db()
    assert title.verified_by_id == (staff.pk if operation == "revoke" else administrator.pk)
    assert title.verified_at == (original if operation == "revoke" else now)
    user.refresh_from_db()
    assert not user.is_staff and user.rating == 1000  # Titles confer no account authority or Elo.


def test_image_review_rolls_back_if_audit_write_fails(user, staff, category, monkeypatch):
    staff = grant(staff, "library.change_imagesubmission")
    image = ImageSubmission.objects.create(
        submitted_by=user,
        category=category,
        canonical_answer="Test",
        accepted_synonyms=[],
        source="manual",
        external_image_url="https://example.test/image.png",
        license="CC0",
        attribution="Original",
    )
    model_admin = admin.site._registry[ImageSubmission]

    def fail(*args):
        raise RuntimeError("Audit storage unavailable")

    monkeypatch.setattr(model_admin, "log_change", fail)
    with pytest.raises(RuntimeError):
        model_admin.approve(request_for(staff), ImageSubmission.objects.filter(pk=image.pk))
    image.refresh_from_db()
    assert image.status == "pending" and image.reviewed_by_id is None
