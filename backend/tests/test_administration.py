import uuid
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as ModelValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from accounts.models import User, VerifiedTitle
from games.models import Match, Participant, RankedQueue, Round
from games.services import approved_images
from library.models import ImageSubmission, ImportBatch, ImportItem
from moderation.administration import manage_player, review_image
from moderation.models import Activity, StaffAnnouncement
from moderation.permissions import is_administrator
from moderation.services import account_restrictions
from moderation.workspace import issue

ROOT = "/api/moderation/workspace/administration/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator(db):
    return User.objects.create_superuser(
        username="panel_admin",
        email="panel-admin@example.test",
        password="panel-test-password-734!",
    )


@pytest.fixture
def moderator(db):
    user = User.objects.create_user(username="panel_mod", email="panel-mod@example.test")
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="moderation", codename="access_workspace")
    )
    return user


@pytest.fixture(autouse=True)
def storage(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "private"
    settings.PEXELS_PROTOTYPE_METADATA = True


def authenticate(client, user):
    client.force_authenticate(user)


def upload(name="test.png", color="red", format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (160, 120), color).save(buffer, format=format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/" + format.lower())


def add_image(client, administrator, category, color="red"):
    authenticate(client, administrator)
    batch = client.post(ROOT + "imports/", {"name": "Test collection"}, format="json").json()
    result = client.post(
        ROOT + f"imports/{batch['id']}/",
        {"request_id": str(uuid.uuid4()), "file": upload(color=color)},
        format="multipart",
    )
    assert result.status_code == 201, result.content
    image = ImageSubmission.objects.get(pk=result.json()["image"]["id"])
    response = client.post(
        ROOT + f"images/{image.pk}/",
        {
            "canonical_answer": color + " picture",
            "accepted_synonyms": [color],
            "category": category.pk,
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    return ImageSubmission.objects.get(pk=image.pk)


@pytest.mark.parametrize(
    "path", ["", "staff/", "players/", "images/", "imports/", "audit/", "health/"]
)
@pytest.mark.parametrize(
    "role", ["guest", "player", "moderator", "staff", "superuser_without_staff", "inactive"]
)
def test_administrator_read_boundaries(client, user, moderator, staff, administrator, path, role):
    actor = {
        "player": user,
        "moderator": moderator,
        "staff": staff,
        "superuser_without_staff": administrator,
        "inactive": administrator,
    }.get(role)
    if role == "superuser_without_staff":
        administrator.is_staff = False
        administrator.save(update_fields=["is_staff"])
    if role == "inactive":
        administrator.is_active = False
        administrator.save(update_fields=["is_active"])
    if actor:
        authenticate(client, actor)
    assert client.get(ROOT + path).status_code == 403


def test_administrator_requires_both_flags_and_respects_closure(client, administrator):
    assert is_administrator(administrator)
    authenticate(client, administrator)
    with patch("moderation.administration_views.health", return_value=[]):
        assert client.get(ROOT).status_code == 200
    other = User.objects.create_superuser(username="other_admin", email="other-admin@example.test")
    issue(other, administrator.pk, {"kind": "closed", "category": "integrity"})
    assert client.get(ROOT + "images/").status_code == 403


@pytest.mark.parametrize(
    "operation,body",
    [
        ("rating", {"rating": 1400, "reason": "Crafted request"}),
        ("title", {"title": "legend"}),
        ("moderator", {"enabled": True}),
        ("reopen", {"reason": "Crafted request"}),
    ],
)
def test_native_moderators_cannot_call_administrator_writes(
    client, moderator, user, operation, body
):
    authenticate(client, moderator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/", {"operation": operation, **body}, format="json"
        ).status_code
        == 403
    )
    with pytest.raises(PermissionDenied):
        manage_player(moderator, user.pk, operation, body)
    user.refresh_from_db()
    assert user.rating == 1000 and not user.is_staff
    assert not Activity.objects.filter(action__startswith="admin_").exists()


def test_django_admin_web_forms_cannot_change_administrator_flags(administrator, user):
    from django.contrib import admin
    from django.test import RequestFactory

    model_admin = admin.site._registry[User]
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = administrator
    assert {"is_staff", "is_superuser"} <= set(model_admin.get_readonly_fields(request, user))
    user.is_superuser = True
    with pytest.raises(ModelValidationError, match="command-line-only"):
        model_admin.save_model(request, user, None, True)
    with pytest.raises(ModelValidationError, match="command-line-only"):
        model_admin.delete_queryset(request, User.objects.filter(pk=administrator.pk))


def test_roles_directory_promotion_and_demotion_are_audited(client, administrator, moderator, user):
    authenticate(client, administrator)
    rows = client.get(ROOT + "staff/").json()["results"]
    assert {row["username"] for row in rows} == {administrator.username, moderator.username}
    assert all(row["assigned_at"] is None for row in rows)
    url = ROOT + f"players/{user.pk}/"
    assert (
        client.post(url, {"operation": "moderator", "enabled": True}, format="json").status_code
        == 200
    )
    user.refresh_from_db()
    assert (
        user.has_perm("moderation.access_workspace") and not user.is_staff and not user.is_superuser
    )
    assert Activity.objects.filter(user=user, action="admin_moderator").get().changes["before"] == {
        "moderator": False
    }
    assert (
        client.post(url, {"operation": "moderator", "enabled": False}, format="json").status_code
        == 200
    )
    user = User.objects.get(pk=user.pk)
    assert not user.has_perm("moderation.access_workspace")
    assert (
        client.post(
            ROOT + f"players/{administrator.pk}/",
            {"operation": "moderator", "enabled": False},
            format="json",
        ).status_code
        == 400
    )


@pytest.mark.parametrize("field", ["is_staff", "is_superuser", "password", "email"])
def test_web_administrator_assignment_and_sensitive_fields_rejected(
    client, administrator, user, field
):
    authenticate(client, administrator)
    assert (
        client.post(
            ROOT + f"players/{user.pk}/",
            {"operation": "moderator", "enabled": True, field: True},
            format="json",
        ).status_code
        == 400
    )
    user.refresh_from_db()
    assert not user.is_staff and not user.is_superuser


def test_rating_override_queue_rank_history_and_audit(client, administrator, user):
    from games.ranked_rules import tier

    queue = RankedQueue.objects.create(
        user=user, queued_at=timezone.now(), rating_snapshot=user.rating
    )
    match = Match.objects.create(mode="ranked", status="complete")
    participant = Participant.objects.create(
        match=match, user=user, rating_before=1000, rating_after=1020
    )
    manage_player(administrator, user.pk, "rating", {"rating": 1700, "reason": "Test correction"})
    user.refresh_from_db()
    queue.refresh_from_db()
    participant.refresh_from_db()
    assert user.rating == queue.rating_snapshot == 1700 and tier(user.rating) == "gold"
    assert participant.rating_after == 1020
    entry = Activity.objects.get(action="admin_rating")
    assert entry.actor_id == administrator.pk and entry.user_id == user.pk
    assert (
        entry.changes == {"before": {"rating": 1000}, "after": {"rating": 1700}}
        and entry.reason == "Test correction"
    )
    authenticate(client, user)
    assert client.get("/api/auth/me/").json()["user"]["ranked_tier"] == "gold"


@pytest.mark.parametrize("rating", [99, 2_147_483_648, True, 1.5])
def test_rating_override_bounds(administrator, user, rating):
    with pytest.raises(ValidationError):
        manage_player(
            administrator, user.pk, "rating", {"rating": rating, "reason": "Check bounds"}
        )


def test_rating_override_does_not_modify_active_duel_snapshots(administrator, user):
    match = Match.objects.create(mode="ranked", status="active")
    Participant.objects.create(match=match, user=user, rating_before=1000)
    with pytest.raises(ValidationError, match="active duel"):
        manage_player(administrator, user.pk, "rating", {"rating": 1200, "reason": "Wait"})


def test_reopen_retains_other_sanctions_and_emits_safe_notice(client, administrator, user):
    closure = issue(
        administrator,
        user.pk,
        {"kind": "closed", "category": "integrity", "reason": "Original closure"},
    )
    probation = issue(administrator, user.pk, {"kind": "probation", "category": "fair_play"})
    with pytest.raises(ValidationError):
        manage_player(administrator, user.pk, "reopen", {"reason": ""})
    manage_player(administrator, user.pk, "reopen", {"reason": "PRIVATE review reason"})
    closure.refresh_from_db()
    probation.refresh_from_db()
    assert closure.revoked_at and closure.reason == "Original closure" and not probation.revoked_at
    assert not account_restrictions(user)["blocked"] and account_restrictions(user)["probation"]
    authenticate(client, user)
    body = client.get("/api/moderation/notices/").json()
    assert "reopened" in body["updates"][0]["message"] and "PRIVATE" not in str(body)


def test_titles_exclusive_replacement_removal_and_audit(client, administrator, user):
    for title in ["pro", "master", "legend", ""]:
        manage_player(administrator, user.pk, "title", {"title": title})
        user.refresh_from_db()
        authenticate(client, user)
        assert client.get("/api/auth/me/").json()["user"]["title"] == (title or None)
        assert VerifiedTitle.objects.filter(user=user).count() == 1
    assert Activity.objects.filter(action="admin_title", user=user).count() == 4
    user.refresh_from_db()
    assert user.rating == 1000 and not user.is_staff


def test_announcements_permissions_version_and_expiration(client, administrator, moderator):
    url = ROOT + "announcement/"
    authenticate(client, moderator)
    assert client.get(url).json() == {"announcement": None}
    body = {
        "title": "Staff note",
        "body": "<script>plain text</script>",
        "published": True,
        "expires_at": None,
        "version": 0,
    }
    assert client.post(url, body, format="json").status_code == 403
    authenticate(client, administrator)
    assert client.post(url, body, format="json").status_code == 200
    assert client.post(url, body, format="json").status_code == 400
    authenticate(client, moderator)
    assert client.get(url).json()["announcement"]["body"] == body["body"]
    StaffAnnouncement.objects.update(published=False)
    assert client.get(url).json() == {"announcement": None}
    assert Activity.objects.filter(action="announcement_changed").count() == 1


def test_browser_upload_validation_resume_duplicates_and_pending(client, administrator, category):
    authenticate(client, administrator)
    batch = client.post(ROOT + "imports/", {"name": "Draft batch"}, format="json").json()
    url = ROOT + f"imports/{batch['id']}/"
    request_id = str(uuid.uuid4())
    first = client.post(url, {"request_id": request_id, "file": upload()}, format="multipart")
    assert first.status_code == 201, first.content
    repeated = client.post(url, {"request_id": request_id, "file": upload()}, format="multipart")
    assert repeated.json()["id"] == first.json()["id"]
    duplicate = client.post(
        url, {"request_id": str(uuid.uuid4()), "file": upload(name="copy.png")}, format="multipart"
    )
    assert duplicate.json()["status"] == "duplicate" and ImageSubmission.objects.count() == 1
    image = ImageSubmission.objects.get()
    assert image.status == "pending" and not image.local_import_metadata["label_verified"]
    assert image.attribution == "Pexels" and image.license == "Pexels License"
    failed = client.post(
        url,
        {"request_id": str(uuid.uuid4()), "file": SimpleUploadedFile("bad.jpg", b"broken")},
        format="multipart",
    )
    assert failed.json()["status"] == "failed"
    assert client.get(url).json()["count"] == 3
    assert client.get("/api/library/catalog/").json()["count"] == 0
    result = client.post(
        ROOT + "images/review/", {"operation": "approve", "ids": [str(image.pk)]}, format="json"
    ).json()
    assert result["results"][0]["status"] == "failed"


def test_image_edit_reviews_retire_restore_and_private_reveal(
    client, administrator, moderator, category
):
    image = add_image(client, administrator, category)
    before_name = image.image_file.name
    result = client.post(
        ROOT + "images/review/", {"operation": "approve", "ids": [str(image.pk)]}, format="json"
    ).json()
    assert result["results"][0]["status"] == "success"
    assert image.pk in {row.pk for row in approved_images()}
    match = Match.objects.create(mode="singleplayer", status="complete")
    history = Round.objects.create(
        match=match,
        image=image,
        number=1,
        answer_snapshot="old answer",
        synonyms_snapshot=["old"],
        image_storage_name=before_name,
    )
    assert (
        client.post(
            ROOT + f"images/{image.pk}/",
            {
                "canonical_answer": "new answer",
                "accepted_synonyms": ["new"],
                "category": category.pk,
            },
            format="json",
        ).status_code
        == 200
    )
    history.refresh_from_db()
    assert history.answer_snapshot == "old answer" and history.image_storage_name == before_name
    assert client.get(ROOT + f"images/{image.pk}/preview/?reveal=200").status_code == 200
    review_image(administrator, image.pk, "retire")
    assert client.get("/api/library/catalog/").json()["count"] == 0
    assert ImageSubmission.objects.get(pk=image.pk).image_file.name == before_name
    review_image(administrator, image.pk, "restore")
    assert client.get("/api/library/catalog/").json()["count"] == 1
    authenticate(client, moderator)
    assert client.get(ROOT + f"images/{image.pk}/preview/").status_code == 403
    assert client.get(f"/api/library/submissions/{image.pk}/preview/").status_code == 403


def test_bulk_results_are_explicit_and_rejection_requires_reason(client, administrator, category):
    image = add_image(client, administrator, category)
    result = client.post(
        ROOT + "images/review/",
        {"operation": "approve", "ids": [str(image.pk), str(uuid.uuid4())]},
        format="json",
    ).json()
    assert [row["status"] for row in result["results"]] == ["success", "failed"]
    assert (
        client.post(
            ROOT + "images/review/", {"operation": "reject", "ids": [str(image.pk)]}, format="json"
        ).status_code
        == 400
    )
    result = client.post(
        ROOT + "images/review/",
        {"operation": "reject", "ids": [str(image.pk)], "reason": "Ambiguous subject"},
        format="json",
    ).json()
    assert result["results"][0]["status"] == "success"
    assert Activity.objects.get(action="image_reject").reason == "Ambiguous subject"


def test_upload_outer_audit_failure_cleans_new_file(client, administrator, category):
    authenticate(client, administrator)
    batch = ImportBatch.objects.create(created_by=administrator, name="Rollback")
    from moderation.administration_imports import upload_item

    with (
        patch("moderation.administration_imports.audit", side_effect=RuntimeError("Audit failed")),
        pytest.raises(RuntimeError),
    ):
        upload_item(administrator, batch.pk, uuid.uuid4(), upload())
    assert not ImageSubmission.objects.exists() and not ImportItem.objects.exists()
    from django.core.files.storage import default_storage

    assert not default_storage.exists("images") or not default_storage.listdir("images")[1]


def test_audit_read_only_health_sanitized_and_csrf(client, administrator, user):
    authenticate(client, administrator)
    manage_player(administrator, user.pk, "rating", {"rating": 1200, "reason": "Audit search"})
    rows = client.get(ROOT + "audit/?action=admin_rating&q=Audit").json()["results"]
    assert len(rows) == 1 and rows[0]["target_id"] == str(user.pk)
    assert client.post(ROOT + "audit/", {}, format="json").status_code == 405
    with patch(
        "moderation.administration_health.database", side_effect=RuntimeError("SECRET password")
    ):
        body = client.get(ROOT + "health/").json()
    assert "SECRET" not in str(body) and any(
        row["state"] == "Unavailable" for row in body["checks"]
    )
    csrf = APIClient(enforce_csrf_checks=True)
    csrf.force_login(administrator)
    assert (
        csrf.post(
            ROOT + f"players/{user.pk}/", {"operation": "title", "title": "pro"}, format="json"
        ).status_code
        == 403
    )


def test_last_playable_image_retirement_preserves_active_game(client, administrator, category):
    image = add_image(client, administrator, category)
    review_image(administrator, image.pk, "approve")
    Match.objects.create(mode="party", status="active")
    with pytest.raises(ValidationError, match="at least one playable"):
        review_image(administrator, image.pk, "retire")
    image.refresh_from_db()
    assert image.retired_at is None
    assert image.pk in {row.pk for row in approved_images()}


def test_label_confirmation_is_audited_even_without_text_changes(client, administrator, category):
    image = add_image(client, administrator, category)
    image.local_import_metadata["label_verified"] = False
    image.save(update_fields=["local_import_metadata"])
    Activity.objects.filter(action="image_edited").delete()
    response = client.post(
        ROOT + f"images/{image.pk}/",
        {
            "canonical_answer": image.canonical_answer,
            "accepted_synonyms": image.accepted_synonyms,
            "category": category.pk,
        },
        format="json",
    )
    assert response.status_code == 200
    event = Activity.objects.get(action="image_edited")
    assert event.changes["before"]["label_verified"] is False
    assert event.changes["after"]["label_verified"] is True


@pytest.mark.parametrize(
    "state,expected",
    [
        ("inactive", "Inactive"),
        ("closed", "Closed"),
        ("suspension", "Suspended"),
        ("probation", "Probation"),
    ],
)
def test_staff_directory_reports_relevant_account_status(
    client, administrator, moderator, state, expected
):
    if state == "inactive":
        moderator.is_active = False
        moderator.save(update_fields=["is_active"])
    else:
        issue(administrator, moderator.pk, {"kind": state, "category": "fair_play"})
    authenticate(client, administrator)
    rows = client.get(ROOT + "staff/").json()["results"]
    row = next(row for row in rows if row["id"] == str(moderator.pk))
    assert row["account_status"] == expected and row["role"] == "Moderator"
    assert row["can_remove_moderator"] is True
