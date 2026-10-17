import uuid
from io import BytesIO, StringIO
from unittest.mock import patch

import pytest
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.lifecycle import close_account
from accounts.models import User
from games.models import Guess, Match, Participant, Party, PartyMember, Round
from library.models import ImageSubmission, PendingFileDeletion
from moderation.account_deletion import delete_account
from moderation.administration import manage_player
from moderation.models import Activity, Sanction
from moderation.services import account_restrictions
from moderation.workspace import change_access, issue

pytestmark = pytest.mark.django_db
PASSWORD = "Lifecycle-test-password-734!"
ROOT = "/api/moderation/workspace/administration/"


@pytest.fixture
def administrator():
    return User.objects.create_superuser(
        username="lifecycle_admin", email="lifecycle-admin@example.test", password=PASSWORD
    )


@pytest.fixture(autouse=True)
def private_storage(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "private"


def picture(owner, reviewer, category, status="pending"):
    data = BytesIO()
    Image.new("RGB", (100, 100), "red").save(data, format="WEBP")
    image = ImageSubmission(
        submitted_by=owner,
        category=category,
        canonical_answer="red square",
        accepted_synonyms=["square"],
        source="manual",
        license="CC0",
        attribution="Retained legal credit",
        status=status,
    )
    image.image_file.save("test.webp", ContentFile(data.getvalue()), save=False)
    if status != "pending":
        image.reviewed_at = timezone.now()
        image.reviewed_by = reviewer
    image.save()
    return image


def closed_target(administrator, user):
    return issue(administrator, user.pk, {"kind": "closed", "category": "other"})


def erase_body(user, **changes):
    return {
        "current_password": PASSWORD,
        "reason": "Requested erasure",
        "confirmation": user.username,
        **changes,
    }


@pytest.mark.parametrize(
    "body", [{}, {"current_password": "wrong"}, {"confirmation": "close my account"}]
)
def test_voluntary_closure_invalid_confirmation_or_password(client, user, body):
    client.force_authenticate(user)
    response = client.post(
        "/api/auth/close-account/",
        {"current_password": "a-strong-unique-pass-734", "confirmation": "CLOSE MY ACCOUNT", **body}
        if body
        else {},
        format="json",
    )
    assert response.status_code == 400
    assert not Sanction.objects.exists()


def test_voluntary_closure_preserves_sanctions_invalidates_all_sessions_and_reopens(
    client, administrator, user
):
    probation = issue(administrator, user.pk, {"kind": "probation", "category": "other"})
    first, second = APIClient(), APIClient()
    for browser in [first, second]:
        browser.force_login(user, backend="accounts.backends.AccountBackend")
    closure = close_account(user.pk, "a-strong-unique-pass-734", "CLOSE MY ACCOUNT")
    assert closure.origin == "voluntary" and closure.issued_by_id == user.pk
    assert account_restrictions(user)["blocked"] and account_restrictions(user)["probation"]
    assert first.get("/api/auth/me/").json()["user"] is None
    assert second.get("/api/auth/me/").json()["user"] is None
    assert not Session.objects.exists()
    assert close_account(user.pk, "a-strong-unique-pass-734", "CLOSE MY ACCOUNT").pk == closure.pk
    assert Sanction.objects.filter(kind="closed").count() == 1
    manage_player(administrator, user.pk, "reopen", {})
    probation.refresh_from_db()
    assert not probation.revoked_at and not account_restrictions(user)["blocked"]
    assert Activity.objects.filter(action="voluntary_closure", user=user).exists()


def test_close_endpoint_signs_out_and_cannot_login(client, user):
    client.force_login(user, backend="accounts.backends.AccountBackend")
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    response = client.post(
        "/api/auth/close-account/",
        {"current_password": "a-strong-unique-pass-734", "confirmation": "CLOSE MY ACCOUNT"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == 200
    assert "current_password" not in response.json()
    assert client.get("/api/auth/me/").json()["user"] is None
    token = client.get("/api/auth/csrf/").json()["csrfToken"]
    assert (
        client.post(
            "/api/auth/login/",
            {"username": user.username, "password": "a-strong-unique-pass-734"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        ).status_code
        == 400
    )
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.parametrize("state", ["active", "inactive", "probation", "suspension"])
def test_deletion_requires_genuine_closure(client, administrator, user, state):
    if state == "inactive":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif state != "active":
        issue(administrator, user.pk, {"kind": state, "category": "other"})
    client.force_authenticate(administrator)
    result = client.post(ROOT + f"players/{user.pk}/delete/", erase_body(user), format="json")
    assert result.status_code == 400
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.parametrize(
    "field,value",
    [("current_password", "wrong"), ("reason", ""), ("reason", "   "), ("confirmation", "WRONG")],
)
def test_sensitive_deletion_confirmation_revalidated(client, administrator, user, field, value):
    closed_target(administrator, user)
    client.force_authenticate(administrator)
    result = client.post(
        ROOT + f"players/{user.pk}/delete/", erase_body(user, **{field: value}), format="json"
    )
    assert result.status_code == 400
    assert User.objects.filter(pk=user.pk).exists()
    assert not Activity.objects.filter(action="account_permanently_deleted").exists()
    assert PASSWORD not in result.content.decode()


@pytest.mark.parametrize("role", ["guest", "player", "moderator", "inactive_admin", "closed_admin"])
def test_deletion_administrator_authorization(client, administrator, user, role):
    closed_target(administrator, user)
    actor = User.objects.create_user(
        username="actor", email="actor@example.test", password=PASSWORD
    )
    if role == "moderator":
        change_access(administrator, actor.pk, True)
    elif role in {"inactive_admin", "closed_admin"}:
        actor.is_staff = actor.is_superuser = True
        actor.is_active = role != "inactive_admin"
        actor.save()
        if role == "closed_admin":
            issue(administrator, actor.pk, {"kind": "closed", "category": "other"})
    if role != "guest":
        client.force_authenticate(actor)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/delete/", erase_body(user), format="json"
        ).status_code
        == 403
    )
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.parametrize("target_role", ["self", "admin", "moderator", "staff"])
def test_deletion_protected_targets(client, administrator, user, target_role):
    if target_role == "self":
        other = User.objects.create_superuser(
            username="other_admin", email="other-admin@example.test"
        )
        closed_target(other, administrator)
        target = administrator
    else:
        target = user
        if target_role == "moderator":
            change_access(administrator, target.pk, True)
        else:
            target.is_staff = True
            target.is_superuser = target_role == "admin"
            target.save()
        closed_target(administrator, target)
    client.force_authenticate(administrator)
    result = client.post(ROOT + f"players/{target.pk}/delete/", erase_body(target), format="json")
    assert result.status_code in [400, 403]
    assert User.objects.filter(pk=target.pk).exists()


def test_deletion_preserves_approved_and_shared_game_history(
    client, administrator, user, category, django_capture_on_commit_callbacks
):
    approved = picture(user, administrator, category, "approved")
    pending = picture(user, administrator, category)
    rejected = picture(user, administrator, category, "rejected")
    approved_name, pending_name, rejected_name = (
        approved.image_file.name,
        pending.image_file.name,
        rejected.image_file.name,
    )
    match = Match.objects.create(mode="ranked", status="complete", completed_at=timezone.now())
    erased = Participant.objects.create(
        match=match, user=user, rating_before=1000, rating_after=980
    )
    survivor = Participant.objects.create(
        match=match, user=administrator, rating_before=1000, rating_after=1020, rating_delta=20
    )
    game_round = Round.objects.create(
        match=match,
        image=approved,
        number=1,
        answer_snapshot="original answer",
        image_storage_name=approved_name,
        winner=erased,
        is_decisive=True,
    )
    Guess.objects.create(
        round=game_round, participant=erased, sequence=1, text="private guess", correct=False
    )
    Guess.objects.create(
        round=game_round, participant=survivor, sequence=1, text="other guess", correct=True
    )
    closed_target(administrator, user)
    client.force_authenticate(administrator)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            ROOT + f"players/{user.pk}/delete/",
            erase_body(user, reason=f"Erase {user.username} {user.email}"),
            format="json",
        )
    assert response.status_code == 200, response.content
    assert not User.objects.filter(pk=user.pk).exists()
    approved.refresh_from_db()
    assert (
        approved.submitted_by_id is None
        and approved.status == "approved"
        and approved.image_file.name == approved_name
    )
    assert approved.image_file.storage.exists(approved_name)
    assert approved.attribution == "Retained legal credit" and approved.license == "CC0"
    assert not ImageSubmission.objects.filter(pk__in=[pending.pk, rejected.pk]).exists()
    assert not approved.image_file.storage.exists(
        pending_name
    ) and not approved.image_file.storage.exists(rejected_name)
    erased.refresh_from_db()
    survivor.refresh_from_db()
    game_round.refresh_from_db()
    assert erased.user_id is None and erased.identity_deleted and erased.rating_before is None
    assert survivor.user_id == administrator.pk and survivor.rating_after == 1020
    assert game_round.winner_id == erased.pk and game_round.answer_snapshot == "original answer"
    assert (
        Guess.objects.filter(participant=survivor).count() == 1
        and not Guess.objects.filter(participant=erased).exists()
    )
    assert (
        client.get(f"/api/ranked/history/{administrator.username}/").json()["results"][0][
            "opponent"
        ]
        == "Deleted player"
    )
    event = Activity.objects.get(action="account_permanently_deleted")
    assert user.username not in str(event.changes) + event.reason + event.target_id
    assert (
        user.email not in event.reason
        and event.user_id is None
        and event.actor_id == administrator.pk
    )


def test_deletion_rolls_back_before_files_are_touched(administrator, user, category):
    pending = picture(user, administrator, category)
    closed_target(administrator, user)
    with patch("moderation.account_deletion.audit", side_effect=RuntimeError("test rollback")):
        with pytest.raises(RuntimeError):
            delete_account(administrator, user.pk, erase_body(user))
    assert (
        User.objects.filter(pk=user.pk).exists()
        and ImageSubmission.objects.filter(pk=pending.pk).exists()
    )
    assert pending.image_file.storage.exists(pending.image_file.name)
    assert not PendingFileDeletion.objects.exists()


def test_file_cleanup_failure_is_retryable(
    administrator, user, category, django_capture_on_commit_callbacks
):
    pending = picture(user, administrator, category)
    closed_target(administrator, user)
    with patch(
        "library.file_cleanup.default_storage.delete", side_effect=OSError("private details")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            delete_account(administrator, user.pk, erase_body(user))
    job = PendingFileDeletion.objects.get()
    assert not job.completed_at and job.attempts == 1 and "private details" not in job.last_error
    call_command("cleanup_deleted_files", stdout=StringIO())
    job.refresh_from_db()
    assert job.completed_at and not pending.image_file.storage.exists(pending.image_file.name)


def test_password_reset_command_hashes_validates_and_invalidates_sessions(user):
    browser = APIClient()
    browser.force_login(user, backend="accounts.backends.AccountBackend")
    output = StringIO()
    with patch(
        "accounts.management.commands.reset_player_password.getpass.getpass",
        side_effect=[PASSWORD, PASSWORD],
    ):
        call_command("reset_player_password", username=user.username, stdout=output)
    user.refresh_from_db()
    assert (
        user.check_password(PASSWORD)
        and user.password != PASSWORD
        and PASSWORD not in output.getvalue()
    )
    assert browser.get("/api/auth/me/").json()["user"] is None
    for passwords in [["one", "two"], ["short", "short"]]:
        with patch(
            "accounts.management.commands.reset_player_password.getpass.getpass",
            side_effect=passwords,
        ):
            with pytest.raises(CommandError):
                call_command("reset_player_password", username=user.username, stdout=output)
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_report_reasons_are_required_for_other_and_existing_categories(client, administrator, user):
    client.force_authenticate(user)
    assert (
        client.post(
            "/api/moderation/reports/",
            {"subject": str(administrator.pk), "category": "other"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/moderation/reports/",
            {"subject": str(administrator.pk), "category": "fair_play"},
            format="json",
        ).status_code
        == 400
    )


def test_password_is_rechecked_at_final_close_and_identity_cannot_be_selected(
    client, administrator, user
):
    client.force_authenticate(user)
    password = "a-strong-unique-pass-734"
    assert (
        client.post(
            "/api/auth/verify-closure-password/", {"current_password": password}, format="json"
        ).status_code
        == 204
    )
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    assert (
        client.post(
            "/api/auth/close-account/",
            {"current_password": password, "confirmation": "CLOSE MY ACCOUNT"},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/close-account/",
            {
                "current_password": PASSWORD,
                "confirmation": "CLOSE MY ACCOUNT",
                "user_id": str(administrator.pk),
            },
            format="json",
        ).status_code
        == 400
    )
    assert not Sanction.objects.exists()


@pytest.mark.parametrize("kind", ["warning", "probation", "suspension", "closed"])
def test_administrator_sanctions_without_reason_are_audited_and_voluntary_cannot_be_forged(
    client, administrator, user, kind
):
    client.force_authenticate(administrator)
    response = client.post(
        f"/api/moderation/workspace/players/{user.pk}/sanctions/",
        {"kind": kind, "category": "other"},
        format="json",
    )
    assert response.status_code == 201
    assert Activity.objects.filter(
        user=user, actor=administrator, action="sanction_issued"
    ).exists()
    assert (
        client.post(
            f"/api/moderation/workspace/players/{administrator.pk}/sanctions/",
            {"kind": kind, "origin": "voluntary"},
            format="json",
        ).status_code
        == 403
    )


def test_existing_administrator_player_tools_accept_omitted_routine_reason(
    client, administrator, user
):
    client.force_authenticate(administrator)
    url = ROOT + f"players/{user.pk}/"
    assert (
        client.post(url, {"operation": "rating", "rating": 1300}, format="json").status_code == 200
    )
    assert Activity.objects.get(action="admin_rating").reason == ""
    closed_target(administrator, user)
    assert client.post(url, {"operation": "reopen"}, format="json").status_code == 200
    assert Activity.objects.get(action="admin_reopen").reason == ""


def test_image_rejection_without_reason_is_audited(client, administrator, user, category):
    image = picture(user, administrator, category)
    client.force_authenticate(administrator)
    response = client.post(
        ROOT + "images/review/", {"ids": [str(image.pk)], "operation": "reject"}, format="json"
    )
    assert response.status_code == 200 and response.json()["results"][0]["status"] == "success"
    assert Activity.objects.get(action="image_reject").reason == ""


def test_deletion_removes_owned_solo_only_and_anonymizes_party_members(
    administrator, user, category
):
    from datetime import timedelta

    image = picture(administrator, administrator, category, "approved")
    solo = Match.objects.create(mode="singleplayer", status="complete")
    own = Participant.objects.create(match=solo, user=user)
    Round.objects.create(match=solo, image=image, number=1, winner=own, is_decisive=True)
    party = Party.objects.create(
        code="DEL123", create_request_id=uuid.uuid4(), expires_at=timezone.now() + timedelta(days=1)
    )
    member = PartyMember.objects.create(
        party=party,
        user=user,
        display_name=user.username,
        name_key=user.username.lower(),
        last_seen=timezone.now(),
        left_at=timezone.now(),
    )
    other = PartyMember.objects.create(
        party=party,
        user=administrator,
        display_name="Other staff",
        name_key="other",
        last_seen=timezone.now(),
    )
    shared = Match.objects.create(mode="party", status="complete")
    Participant.objects.create(match=shared, user=user, party_member=member)
    Participant.objects.create(match=shared, user=administrator, party_member=other)
    closed_target(administrator, user)
    result = delete_account(administrator, user.pk, erase_body(user))
    assert result["outcome"]["solo_games_deleted"] == 1
    assert (
        not Match.objects.filter(pk=solo.pk).exists()
        and Match.objects.filter(pk=shared.pk).exists()
    )
    member.refresh_from_db()
    other.refresh_from_db()
    assert (
        member.identity_deleted
        and member.user_id is None
        and member.display_name == "Deleted player"
    )
    assert other.user_id == administrator.pk and other.display_name == "Other staff"


def test_deleted_former_staff_anonymizes_professional_references(administrator, user, category):
    from accounts.models import VerifiedTitle
    from moderation.workspace import reverse

    user.is_staff = True
    user.save(update_fields=["is_staff"])
    other = User.objects.create_user(username="other_player", email="other-player@example.test")
    image = picture(other, user, category, "approved")
    title = VerifiedTitle.objects.create(user=other, title="pro", verified_by=user)
    warning = issue(administrator, other.pk, {"kind": "warning", "category": "other"})
    reverse(administrator, warning.pk)
    Sanction.objects.filter(pk=warning.pk).update(revoked_by=user)
    issued = Sanction.objects.create(user=other, issued_by=user, kind="probation", category="other")
    user.is_staff = False
    user.save(update_fields=["is_staff"])
    closed_target(administrator, user)
    delete_account(administrator, user.pk, erase_body(user))
    image.refresh_from_db()
    warning.refresh_from_db()
    issued.refresh_from_db()
    title.refresh_from_db()
    assert image.reviewed_by_id is None and image.reviewer_deleted and image.status == "approved"
    image.full_clean()
    assert warning.revoked_by_id is None and warning.revoker_deleted and warning.revoked_at
    warning.full_clean()
    assert issued.issued_by_id is None and title.verified_by_id is None
    assert User.objects.filter(pk=other.pk).exists()


def test_shared_approved_storage_is_never_removed(
    administrator, user, category, django_capture_on_commit_callbacks
):
    approved = picture(administrator, administrator, category, "approved")
    ImageSubmission.objects.create(
        submitted_by=user,
        category=category,
        canonical_answer="same stored file",
        source="manual",
        license="CC0",
        attribution="Credit",
        image_file=approved.image_file.name,
    )
    closed_target(administrator, user)
    with django_capture_on_commit_callbacks(execute=True):
        delete_account(administrator, user.pk, erase_body(user))
    assert approved.image_file.storage.exists(approved.image_file.name)
    assert PendingFileDeletion.objects.get().last_error == "Shared file retained."


def test_sensitive_actions_require_real_session_csrf(administrator, user):
    closed_target(administrator, user)
    browser = APIClient(enforce_csrf_checks=True)
    browser.force_login(administrator, backend="accounts.backends.AccountBackend")
    assert (
        browser.post(
            ROOT + f"players/{user.pk}/delete/", erase_body(user), format="json"
        ).status_code
        == 403
    )
    assert User.objects.filter(pk=user.pk).exists()
    browser.force_login(user, backend="accounts.backends.AccountBackend")
    assert (
        browser.post(
            "/api/auth/close-account/",
            {"current_password": "a-strong-unique-pass-734", "confirmation": "CLOSE MY ACCOUNT"},
            format="json",
        ).status_code
        == 403
    )


def test_django_admin_cannot_bypass_sensitive_deletion_or_cli_password_reset(administrator, user):
    from django.contrib import admin
    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory

    model_admin = admin.site._registry[User]
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = administrator
    assert not model_admin.has_delete_permission(request, user)
    with pytest.raises(PermissionDenied):
        model_admin.delete_model(request, user)
    with pytest.raises(PermissionDenied):
        model_admin.user_change_password(request, str(user.pk))
    assert User.objects.filter(pk=user.pk).exists()


def test_cli_refuses_echoing_fallback(user):
    import getpass

    with patch(
        "accounts.management.commands.reset_player_password.getpass.getpass",
        side_effect=getpass.GetPassWarning("no tty"),
    ):
        with pytest.raises(CommandError, match="secure interactive terminal"):
            call_command("reset_player_password", username=user.username)


def test_retired_and_licensed_provenance_stay_unchanged_on_account_deletion(
    administrator, user, category
):
    image = picture(user, administrator, category, "approved")
    image.retired_at = timezone.now()
    image.local_import_metadata = {
        "original_filename": user.username + ".jpg",
        "photographer": "Legal artist",
        "stored_sha256": "integrity",
        "review_notes": user.email,
    }
    image.source_url = "https://example.test/legal-source"
    image.save()
    closed_target(administrator, user)
    delete_account(administrator, user.pk, erase_body(user))
    image.refresh_from_db()
    assert (
        image.status == "approved"
        and image.retired_at
        and image.source_url == "https://example.test/legal-source"
    )
    assert image.local_import_metadata == {
        "photographer": "Legal artist",
        "stored_sha256": "integrity",
    }


@pytest.mark.parametrize("missing", ["current_password", "reason", "confirmation"])
def test_deletion_requires_each_sensitive_field(client, administrator, user, missing):
    closed_target(administrator, user)
    client.force_authenticate(administrator)
    body = erase_body(user)
    body.pop(missing)
    response = client.post(ROOT + f"players/{user.pk}/delete/", body, format="json")
    assert response.status_code == 400
    assert User.objects.filter(pk=user.pk).exists()


def test_deletion_revalidates_stale_actor_and_exact_current_username(administrator, user):
    from rest_framework.exceptions import PermissionDenied, ValidationError

    closed_target(administrator, user)
    old_name = user.username
    User.objects.filter(pk=user.pk).update(username="renamed_target")
    with pytest.raises(ValidationError):
        delete_account(administrator, user.pk, erase_body(user, confirmation=old_name))
    User.objects.filter(pk=administrator.pk).update(is_superuser=False)
    with pytest.raises(PermissionDenied):
        delete_account(administrator, user.pk, erase_body(user, confirmation="renamed_target"))
    assert User.objects.filter(pk=user.pk).exists()


def test_image_review_audits_remove_submitter_identity(administrator, user, category):
    approved = picture(user, administrator, category, "approved")
    event = Activity.objects.create(
        actor=administrator,
        action="image_edited",
        target_type="image",
        target_id=str(approved.pk),
        reason="Submitted by " + user.email,
        changes={"before": {"review_reason": user.username}},
    )
    closed_target(administrator, user)
    delete_account(administrator, user.pk, erase_body(user))
    event.refresh_from_db()
    assert event.actor_id == administrator.pk
    assert user.email not in event.reason and user.username not in str(event.changes)


def test_deletion_defers_when_unapproved_image_is_used_by_active_shared_game(
    administrator, user, category
):
    from rest_framework.exceptions import ValidationError

    pending = picture(user, administrator, category)
    match = Match.objects.create(mode="party", status="active")
    Participant.objects.create(match=match, user=administrator)
    Round.objects.create(match=match, image=pending, number=1)
    closed_target(administrator, user)
    with pytest.raises(ValidationError, match="active game"):
        delete_account(administrator, user.pk, erase_body(user))
    assert User.objects.filter(pk=user.pk).exists()
    assert pending.image_file.storage.exists(pending.image_file.name)
