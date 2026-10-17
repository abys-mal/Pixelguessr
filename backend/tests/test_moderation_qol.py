import uuid
from io import BytesIO, StringIO
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone
from PIL import Image
from rest_framework.exceptions import ValidationError

from accounts.lifecycle import close_account
from accounts.models import User
from games.models import Guess, Match, Participant, Round
from games.services import GameError, approved_images
from library.models import ImageSubmission, ImportBatch, ImportItem, PendingFileDeletion
from moderation.administration import delete_library_image
from moderation.models import Activity, Report
from moderation.workspace import change_access, issue, submit_appeal

pytestmark = pytest.mark.django_db
ROOT = "/api/moderation/workspace/"
ADMIN_ROOT = ROOT + "administration/"


@pytest.fixture
def administrator():
    return User.objects.create_superuser(
        username="qol_admin", email="admin@example.test", password="Quality-password-734!"
    )


@pytest.fixture
def moderator(administrator):
    actor = User.objects.create_user(username="qol_moderator", email="mod@example.test")
    change_access(administrator, actor.pk, True)
    return actor


@pytest.fixture
def photo(administrator, category, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "private"
    data = BytesIO()
    Image.new("RGB", (100, 100), "blue").save(data, format="WEBP")
    image = ImageSubmission(
        submitted_by=administrator,
        category=category,
        canonical_answer="blue",
        source="manual",
        license="CC0",
        attribution="Required credit",
        status="approved",
        reviewed_at=timezone.now(),
        reviewed_by=administrator,
    )
    image.image_file.save("fixture.webp", ContentFile(data.getvalue()), save=False)
    image.save()
    return image


def test_report_success_uses_authenticated_identity_and_existing_staff_queue(
    client, user, moderator
):
    client.force_authenticate(user)
    response = client.post(
        "/api/moderation/reports/",
        {
            "subject": str(moderator.pk),
            "category": "other",
            "details": "Please review this concern.",
        },
        format="json",
    )
    assert response.status_code == 201
    report = Report.objects.get()
    assert report.reporter_id == user.pk and report.subject_id == moderator.pk and report.created_at
    assert "reporter" not in response.json()
    assert Activity.objects.filter(action="report_submitted", actor=user, report=report).exists()
    client.force_authenticate(moderator)
    assert client.get("/api/moderation/notices/").json()["sanctions"] == []
    # A report creates no player-visible notice or sanction.
    assert "reports" not in client.get("/api/moderation/notices/").json()


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "invalid"},
        {"details": ""},
        {"details": "   "},
        {"details": "x" * 2001},
        {"subject": "invalid"},
        {"subject": str(uuid.uuid4())},
        {"reporter": str(uuid.uuid4())},
        {"reporter_id": str(uuid.uuid4())},
    ],
)
def test_report_invalid_inputs_do_not_create_records(client, user, administrator, changes):
    client.force_authenticate(user)
    response = client.post(
        "/api/moderation/reports/",
        {
            "subject": str(administrator.pk),
            "category": "other",
            "details": "A written concern",
            **changes,
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Report.objects.exists()


def test_reporting_requires_authentication_prevents_self_and_duplicate_reports(
    client, user, administrator
):
    data = {"subject": str(administrator.pk), "category": "fair_play", "details": "Please review"}
    assert client.post("/api/moderation/reports/", data, format="json").status_code == 403
    client.force_authenticate(user)
    assert (
        client.post(
            "/api/moderation/reports/", {**data, "subject": str(user.pk)}, format="json"
        ).status_code
        == 400
    )
    assert client.post("/api/moderation/reports/", data, format="json").status_code == 201
    assert client.post("/api/moderation/reports/", data, format="json").status_code == 400
    assert Report.objects.count() == 1


def test_report_rate_limit(client, user):
    client.force_authenticate(user)
    for number in range(11):
        target = User.objects.create_user(
            username=f"reported_{number}", email=f"reported{number}@example.test"
        )
        response = client.post(
            "/api/moderation/reports/",
            {"subject": str(target.pk), "category": "other", "details": "Review please"},
            format="json",
        )
        assert response.status_code == (201 if number < 10 else 429)
    assert Report.objects.count() == 10


@pytest.mark.parametrize(
    "state", ["active", "probation", "suspension", "voluntary", "disciplinary"]
)
def test_player_information_uses_exact_values_and_no_authentication_secrets(
    client, moderator, administrator, user, state
):
    if state == "voluntary":
        close_account(user.pk, "a-strong-unique-pass-734", "CLOSE MY ACCOUNT")
    elif state != "active":
        issue(
            administrator,
            user.pk,
            {"kind": "closed" if state == "disciplinary" else state, "category": "other"},
        )
    client.force_authenticate(moderator)
    response = client.get(ROOT + f"players/{user.pk}/")
    assert response.status_code == 200
    player = response.json()["player"]
    assert player["id"] == str(user.pk) and player["date_joined"] == user.date_joined.isoformat()
    assert player["role"] == "Player" and player["rating"] == user.rating
    expected = {
        "active": "Active",
        "probation": "Probation",
        "suspension": "Suspension",
        "voluntary": "Voluntarily closed",
        "disciplinary": "Disciplinary closure",
    }[state]
    assert expected in player["statuses"]
    for forbidden in ["password", "email", "last_login", "session", "token", "ip_address"]:
        assert forbidden not in player
    client.force_authenticate(user)
    assert client.get(ROOT + f"players/{user.pk}/").status_code == 403


@pytest.mark.parametrize("decision", ["uphold", "reverse"])
@pytest.mark.parametrize(
    "reason", ["", "We reviewed your explanation. <script>alert('x')</script>"]
)
def test_appeal_closing_reason_optional_audited_and_visible_only_to_owner(
    client, administrator, moderator, user, decision, reason
):
    sanction = issue(
        administrator,
        user.pk,
        {"kind": "warning", "category": "other", "internal_note": "Private staff note"},
    )
    appeal = submit_appeal(user, sanction.pk, "Please review.")
    client.force_authenticate(moderator)
    response = client.post(
        ROOT + f"appeals/{appeal.pk}/resolve/",
        {"decision": decision, **({"closing_reason": reason} if reason else {})},
        format="json",
    )
    assert response.status_code == 200
    appeal.refresh_from_db()
    assert appeal.closing_reason == reason and appeal.status == (
        "upheld" if decision == "uphold" else "reversed"
    )
    event = Activity.objects.get(action="appeal_" + appeal.status)
    assert event.changes["closing_reason"] == reason
    client.force_authenticate(user)
    notices = client.get("/api/moderation/notices/").json()
    assert notices["appeals"][0]["closing_reason"] == reason
    assert "Private staff note" not in str(notices)
    client.force_authenticate(administrator)
    assert client.get("/api/moderation/notices/").json()["appeals"] == []
    assert (
        client.post(
            ROOT + f"appeals/{appeal.pk}/resolve/", {"decision": "uphold"}, format="json"
        ).status_code
        == 400
    )


def test_appeal_closing_reason_permissions_and_length(client, administrator, user):
    sanction = issue(administrator, user.pk, {"kind": "warning", "category": "other"})
    appeal = submit_appeal(user, sanction.pk, "Review please")
    client.force_authenticate(user)
    assert (
        client.post(
            ROOT + f"appeals/{appeal.pk}/resolve/", {"decision": "uphold"}, format="json"
        ).status_code
        == 403
    )
    client.force_authenticate(administrator)
    assert (
        client.post(
            ROOT + f"appeals/{appeal.pk}/resolve/",
            {"decision": "uphold", "closing_reason": "x" * 2001},
            format="json",
        ).status_code
        == 400
    )
    appeal.refresh_from_db()
    assert appeal.status == "pending"


@pytest.mark.parametrize("state", ["pending", "approved", "rejected", "retired"])
def test_image_deletion_eligibility_confirmation_and_audit(
    client, administrator, photo, state, django_capture_on_commit_callbacks
):
    photo.status = (
        "rejected" if state == "rejected" else "pending" if state == "pending" else "approved"
    )
    photo.retired_at = timezone.now() if state == "retired" else None
    photo.save()
    client.force_authenticate(administrator)
    url = ADMIN_ROOT + f"images/{photo.pk}/delete/"
    for body in [{}, {"confirm": False}, {"confirm": True, "unexpected": True}]:
        assert client.post(url, body, format="json").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(url, {"confirm": True}, format="json")
    if state in {"rejected", "retired"}:
        assert response.status_code == 200
        assert not ImageSubmission.objects.filter(pk=photo.pk).exists()
        assert not photo.image_file.storage.exists(photo.image_file.name)
        event = Activity.objects.get(action="image_permanently_deleted")
        assert event.actor_id == administrator.pk and event.target_id == str(photo.pk)
        assert event.changes == {"before": {}, "after": {"deleted": True}}
        assert photo.image_file.name not in str(event.changes)
    else:
        assert response.status_code == 400 and ImageSubmission.objects.filter(pk=photo.pk).exists()


@pytest.mark.parametrize("role", ["guest", "player", "moderator", "inactive_admin"])
def test_image_deletion_requires_active_administrator(
    client, administrator, moderator, user, photo, role
):
    photo.retired_at = timezone.now()
    photo.save()
    if role == "inactive_admin":
        administrator.is_active = False
        administrator.save()
        actor = administrator
    else:
        actor = moderator if role == "moderator" else user
    if role != "guest":
        client.force_authenticate(actor)
    assert (
        client.post(
            ADMIN_ROOT + f"images/{photo.pk}/delete/", {"confirm": True}, format="json"
        ).status_code
        == 403
    )
    assert ImageSubmission.objects.filter(pk=photo.pk).exists()


def test_image_deletion_preserves_history_other_images_and_batches(
    administrator, user, photo, category, django_capture_on_commit_callbacks
):
    photo.retired_at = timezone.now()
    photo.save()
    other = ImageSubmission.objects.create(
        submitted_by=administrator,
        category=category,
        canonical_answer="other",
        source="manual",
        license="CC0",
        attribution="Credit",
        external_image_url="https://example.test/other",
    )
    match = Match.objects.create(mode="ranked", status="complete", completed_at=timezone.now())
    participant = Participant.objects.create(match=match, user=user, total_score=900)
    game_round = Round.objects.create(
        match=match,
        image=photo,
        number=1,
        answer_snapshot="blue",
        image_storage_name=photo.image_file.name,
        ended_at=timezone.now(),
        outcome="solved",
        winner=participant,
        is_decisive=True,
    )
    guess = Guess.objects.create(
        round=game_round,
        participant=participant,
        text="blue",
        correct=True,
        sequence=1,
    )
    batch = ImportBatch.objects.create(name="Keep batch", created_by=administrator)
    ImportItem.objects.create(
        batch=batch,
        image=photo,
        request_id=uuid.uuid4(),
        filename="removed.webp",
        status="uploaded",
    )
    survivor = ImportItem.objects.create(
        batch=batch, image=other, request_id=uuid.uuid4(), filename="keep.webp", status="uploaded"
    )
    with django_capture_on_commit_callbacks(execute=True):
        delete_library_image(administrator, photo.pk, True)
    game_round.refresh_from_db()
    participant.refresh_from_db()
    assert game_round.image_id is None and game_round.image_storage_name == ""
    assert game_round.answer_snapshot == "blue" and game_round.winner_id == participant.pk
    assert game_round.image_metadata_snapshot == {
        "license": "CC0",
        "attribution": "Required credit",
        "category": category.name,
    }
    assert participant.total_score == 900 and Guess.objects.filter(pk=guess.pk).exists()
    assert (
        Match.objects.filter(pk=match.pk).exists()
        and ImportBatch.objects.filter(pk=batch.pk).exists()
    )
    assert (
        ImportItem.objects.filter(pk=survivor.pk).exists()
        and ImageSubmission.objects.filter(pk=other.pk).exists()
    )
    with pytest.raises(GameError, match="No approved hosted images"):
        approved_images()


def test_image_deletion_rollback_and_cleanup_retry(
    administrator, photo, django_capture_on_commit_callbacks
):
    photo.retired_at = timezone.now()
    photo.save()
    with patch("moderation.administration.audit", side_effect=RuntimeError("rollback")):
        with pytest.raises(RuntimeError):
            delete_library_image(administrator, photo.pk, True)
    assert (
        photo.image_file.storage.exists(photo.image_file.name)
        and ImageSubmission.objects.filter(pk=photo.pk).exists()
    )
    assert not PendingFileDeletion.objects.exists()
    with patch(
        "library.file_cleanup.default_storage.delete", side_effect=OSError("storage unavailable")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            delete_library_image(administrator, photo.pk, True)
    job = PendingFileDeletion.objects.get()
    assert not job.completed_at and job.attempts == 1
    call_command("cleanup_deleted_files", stdout=StringIO())
    job.refresh_from_db()
    assert job.completed_at and not photo.image_file.storage.exists(photo.image_file.name)


def test_image_deletion_defers_during_live_reveal(administrator, photo):
    photo.retired_at = timezone.now()
    photo.save()
    match = Match.objects.create(mode="party", status="active")
    Round.objects.create(
        match=match,
        image=photo,
        number=1,
        reveal_started_at=timezone.now(),
        image_storage_name=photo.image_file.name,
    )
    with pytest.raises(ValidationError, match="active game"):
        delete_library_image(administrator, photo.pk, True)
    assert ImageSubmission.objects.filter(pk=photo.pk).exists() and photo.image_file.storage.exists(
        photo.image_file.name
    )


def test_deleted_image_shared_file_is_retained(
    administrator, photo, category, django_capture_on_commit_callbacks
):
    photo.retired_at = timezone.now()
    photo.save()
    other = ImageSubmission.objects.create(
        submitted_by=administrator,
        category=category,
        canonical_answer="Other image",
        image_file=photo.image_file.name,
        status="approved",
        reviewed_by=administrator,
        reviewed_at=timezone.now(),
        source="manual",
        license="CC0",
        attribution="Credit",
    )
    with django_capture_on_commit_callbacks(execute=True):
        delete_library_image(administrator, photo.pk, True)
    assert other.image_file.storage.exists(other.image_file.name)
    assert PendingFileDeletion.objects.get().last_error == "Shared file retained."


def test_file_deletion_waits_for_commit(administrator, photo):
    photo.retired_at = timezone.now()
    photo.save()
    delete_library_image(administrator, photo.pk, True)
    assert photo.image_file.storage.exists(photo.image_file.name)
    assert PendingFileDeletion.objects.get().completed_at is None


def test_image_delete_and_public_report_require_session_csrf(administrator, user, photo):
    from rest_framework.test import APIClient

    photo.retired_at = timezone.now()
    photo.save()
    browser = APIClient(enforce_csrf_checks=True)
    browser.force_login(administrator, backend="accounts.backends.AccountBackend")
    assert (
        browser.post(
            ADMIN_ROOT + f"images/{photo.pk}/delete/", {"confirm": True}, format="json"
        ).status_code
        == 403
    )
    browser.force_login(user, backend="accounts.backends.AccountBackend")
    assert (
        browser.post(
            "/api/moderation/reports/",
            {"subject": str(administrator.pk), "category": "other", "details": "Review please"},
            format="json",
        ).status_code
        == 403
    )
    assert ImageSubmission.objects.filter(pk=photo.pk).exists() and not Report.objects.exists()
