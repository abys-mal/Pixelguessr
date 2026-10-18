import importlib
import uuid
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from games.models import Guess, Match, Participant, Round
from games.services import approved_images
from library.contributions import create_contribution
from library.models import (
    ImageSubmission,
    ImportBatch,
    ImportItem,
    PendingFileDeletion,
    RemovedContribution,
)
from library.serializers import ContributionInput, SubmissionSerializer
from moderation.account_deletion import delete_account
from moderation.administration import delete_library_image
from moderation.models import Activity
from moderation.workspace import change_access, issue

pytestmark = pytest.mark.django_db
ROOT = "/api/library/contributions/"
ADMIN = "/api/moderation/workspace/administration/"


@pytest.fixture
def administrator():
    return User.objects.create_superuser(
        username="contribution_admin",
        email="contribution-admin@example.test",
        password="Contribution-password-734!",
    )


@pytest.fixture
def contribution(client, user, uploaded_submission):
    client.force_authenticate(user)
    response = client.post(ROOT, uploaded_submission(), format="multipart")
    assert response.status_code == 201, response.content
    return ImageSubmission.objects.get(pk=response.json()["id"])


def review(client, administrator, image, operation, **data):
    client.force_authenticate(administrator)
    return client.post(
        ADMIN + f"player-submissions/{image.pk}/review/",
        {"operation": operation, **data},
        format="json",
    )


def test_upload_is_one_pending_private_webp_with_explicit_rights(client, user, uploaded_submission):
    client.force_authenticate(user)
    response = client.post(ROOT, uploaded_submission(), format="multipart")
    assert response.status_code == 201
    image = ImageSubmission.objects.get()
    assert image.status == "pending" and image.player_contribution and image.rights_acknowledged_at
    assert image.submitted_by_id == user.pk and image.image_file.name.endswith(".webp")
    assert "panda" not in image.image_file.name and "secret-answer" not in image.image_file.name
    assert image.image_file.storage.exists(image.image_file.name)
    assert client.get("/api/library/catalog/").json()["count"] == 0
    assert "image_file" not in response.json() and "local_import_metadata" not in response.json()


@pytest.mark.parametrize(
    "changes",
    [
        {"rights_acknowledged": "false"},
        {"external_image_url": "https://example.test/image.png"},
        {"status": "approved"},
        {"submitted_by": str(uuid.uuid4())},
        {"player_contribution": False},
        {"source_url": "http://example.test/source"},
        {"license": ""},
        {"attribution": ""},
        {"canonical_answer": ""},
        {"accepted_synonyms": '"bad"'},
    ],
)
def test_invalid_or_forged_upload_fields_rejected(client, user, uploaded_submission, changes):
    client.force_authenticate(user)
    assert client.post(ROOT, uploaded_submission(**changes), format="multipart").status_code == 400
    assert not ImageSubmission.objects.exists()


def test_missing_file_acknowledgment_and_legacy_write_bypass_are_rejected(
    client, user, uploaded_submission
):
    client.force_authenticate(user)
    for missing in ["image_file", "rights_acknowledged"]:
        body = uploaded_submission()
        body.pop(missing)
        assert client.post(ROOT, body, format="multipart").status_code == 400
    body = uploaded_submission(rights_acknowledged="false")
    assert client.post("/api/library/submissions/", body, format="multipart").status_code == 400
    assert not ImageSubmission.objects.exists()


@pytest.mark.parametrize("kind", ["probation", "suspension"])
def test_restricted_players_can_read_their_history_but_not_create(
    client, user, administrator, contribution, uploaded_submission, kind
):
    issue(administrator, user.pk, {"kind": kind, "category": "other"})
    client.force_authenticate(user)
    assert client.get(ROOT).status_code == 200
    assert client.get(ROOT + f"{contribution.pk}/").status_code == 200
    assert client.post(ROOT, uploaded_submission(), format="multipart").status_code == 403


def test_contribution_private_read_only_scope_and_previews(
    client, user, administrator, contribution
):
    client.force_authenticate(user)
    url = ROOT + f"{contribution.pk}/"
    assert client.get(url).status_code == 200
    preview = client.get(url + "preview/")
    assert preview.status_code == 200 and "no-store" in preview["Cache-Control"]
    for method in ["patch", "put", "delete"]:
        assert (
            getattr(client, method)(url, {"status": "approved"}, format="json").status_code == 405
        )
    outsider = User.objects.create_user(username="outsider", email="outsider@example.test")
    client.force_authenticate(outsider)
    assert client.get(ROOT).json()["count"] == 0
    assert client.get(url).status_code == 404 and client.get(url + "preview/").status_code == 404
    client.force_authenticate(administrator)
    assert client.get(url + "preview/").status_code == 200
    client.force_authenticate(None)
    assert client.get(ROOT).status_code == 403 and client.get(url).status_code == 403


def test_paginated_combined_history_and_stats_are_not_limited_to_24(client, user, contribution):
    ImageSubmission.objects.bulk_create(
        [
            ImageSubmission(
                submitted_by=user,
                player_contribution=True,
                canonical_answer=f"answer {n}",
                category=contribution.category,
                source="manual",
                external_image_url="https://example.test/picture",
                license="CC0",
                attribution="Credit",
            )
            for n in range(27)
        ]
    )
    receipt = RemovedContribution.objects.create(submitted_by=user, created_at=timezone.now())
    response = client.get(ROOT)
    assert response.status_code == 200, response.content
    assert response.json()["stats"] == {"total": 29, "pending": 28, "approved": 0}
    assert len(response.json()["results"]) == 24 and response.json()["next"]
    page2 = client.get(ROOT + "?page=2").json()
    assert len(page2["results"]) == 5
    removed = client.get(ROOT + "?status=removed").json()
    assert removed["count"] == 1 and set(removed["results"][0]) == {"id", "status", "created_at"}
    assert removed["results"][0]["id"] == str(receipt.pk)
    assert client.get(ROOT + "?status=forged").status_code == 400


def test_administrator_review_is_single_stage_and_accepts_corrections(
    client, user, administrator, contribution
):
    old_pk = contribution.pk
    old_file = contribution.image_file.name
    response = review(
        client,
        administrator,
        contribution,
        "approve",
        corrections={
            "canonical_answer": "blue square",
            "accepted_synonyms": ["square"],
            "category": contribution.category_id,
            "source": "manual",
            "source_url": "",
            "license": "CC0",
            "attribution": "Corrected credit",
        },
    )
    assert response.status_code == 200, response.content
    contribution.refresh_from_db()
    assert (
        contribution.pk == old_pk
        and contribution.status == "approved"
        and ImageSubmission.objects.count() == 1
    )
    assert (
        contribution.image_file.name == old_file and contribution.canonical_answer == "blue square"
    )
    assert contribution.reviewed_by_id == administrator.pk and contribution.reviewed_at
    assert approved_images()[0].pk == contribution.pk
    assert Activity.objects.filter(action="image_approve", target_id=str(contribution.pk)).exists()
    client.force_authenticate(user)
    assert client.get(ROOT).json()["stats"]["approved"] == 1
    assert review(client, administrator, contribution, "approve").status_code == 400


@pytest.mark.parametrize("visible", [False, True])
def test_rejection_feedback_is_explicitly_player_visible_only(
    client, user, administrator, contribution, visible
):
    response = review(
        client,
        administrator,
        contribution,
        "reject",
        explanation="Private or public review context",
        visible_to_player=visible,
    )
    assert response.status_code == 200
    contribution.refresh_from_db()
    assert contribution.status == "rejected" and contribution.image_file.storage.exists(
        contribution.image_file.name
    )
    client.force_authenticate(user)
    detail = client.get(ROOT + f"{contribution.pk}/").json()
    assert detail["explanation"] == ("Private or public review context" if visible else "")
    assert "review_reason" not in detail and "import_metadata" not in detail
    assert client.get("/api/library/catalog/").json()["count"] == 0


def test_rejection_needs_no_reason(client, administrator, contribution):
    assert review(client, administrator, contribution, "reject").status_code == 200


def test_player_review_lifecycle_enters_library_only_after_approval(
    client, administrator, contribution
):
    client.force_authenticate(administrator)
    pk = str(contribution.pk)
    stored = contribution.image_file.name
    assert client.get(ADMIN + "images/").json()["count"] == 0
    inbox = client.get(ADMIN + "player-submissions/?status=pending").json()
    assert [row["id"] for row in inbox["results"]] == [pk]
    assert client.get(inbox["results"][0]["preview_url"]).status_code == 200

    assert review(client, administrator, contribution, "approve").status_code == 200
    for path in ["images/", "images/?status=approved", "player-submissions/?status=approved"]:
        result = client.get(ADMIN + path).json()
        assert result["count"] == 1 and result["results"][0]["id"] == pk
    contribution.refresh_from_db()
    assert ImageSubmission.objects.count() == 1 and contribution.image_file.name == stored
    assert approved_images()[0].pk == contribution.pk

    for operation, status in [("retire", "retired"), ("restore", "approved")]:
        response = client.post(
            ADMIN + "images/review/", {"ids": [pk], "operation": operation}, format="json"
        )
        assert response.json()["results"][0]["status"] == "success"
        assert client.get(ADMIN + f"images/?status={status}").json()["count"] == 1
        assert client.get(ADMIN + "player-submissions/?status=approved").json()["count"] == 1
    assert ImageSubmission.objects.count() == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_hidden_player_submissions_cannot_enter_library_via_search_or_bulk_review(
    client, administrator, contribution, status
):
    if status == "rejected":
        assert review(client, administrator, contribution, "reject").status_code == 200
    client.force_authenticate(administrator)
    pk = str(contribution.pk)
    for query in ["", f"?status={status}", f"?q={pk}", "?q=panda", "?q=nature"]:
        result = client.get(ADMIN + "images/" + query).json()
        assert result["count"] == 0 and result["results"] == []
    assert client.get(ADMIN + f"images/{pk}/").status_code == 404
    assert (
        client.post(
            ADMIN + f"images/{pk}/",
            {
                "canonical_answer": "Changed",
                "accepted_synonyms": [],
                "category": contribution.category_id,
            },
            format="json",
        ).status_code
        == 404
    )
    for operation in ["approve", "reject", "retire", "restore"]:
        result = client.post(
            ADMIN + "images/review/", {"ids": [pk], "operation": operation}, format="json"
        ).json()
        assert result["results"][0]["status"] == "failed"
    contribution.refresh_from_db()
    assert contribution.status == status and not contribution.retired_at
    assert contribution.canonical_answer != "Changed"
    assert client.get(ADMIN + f"player-submissions/?status={status}").json()["count"] == 1


def test_library_pagination_counts_metrics_and_pending_import_workflow(
    client, administrator, contribution
):
    # Same source and even the same submitter: the server-controlled origin marker is decisive.
    imported = ImageSubmission.objects.create(
        submitted_by=contribution.submitted_by,
        category=contribution.category,
        canonical_answer="imported panda",
        source=contribution.source,
        image_file=contribution.image_file.name,
        license="CC0",
        attribution="Import credit",
    )
    batch = ImportBatch.objects.create(created_by=administrator, name="Pending import batch")
    ImportItem.objects.create(
        batch=batch,
        image=imported,
        request_id=uuid.uuid4(),
        filename="private.png",
        status="uploaded",
    )
    ImageSubmission.objects.bulk_create(
        [
            ImageSubmission(
                category=contribution.category,
                canonical_answer=f"Library image {index}",
                external_image_url="https://example.test/image",
                source="manual",
                license="CC0",
                attribution="Credit",
            )
            for index in range(25)
        ]
    )
    client.force_authenticate(administrator)
    first = client.get(ADMIN + "images/").json()
    second = client.get(ADMIN + "images/?page=2").json()
    assert first["count"] == second["count"] == 26
    assert len(first["results"]) == 24 and len(second["results"]) == 2
    assert str(contribution.pk) not in {row["id"] for row in first["results"] + second["results"]}
    assert client.get(ADMIN + "images/?status=pending").json()["count"] == 26
    assert client.get(ADMIN + "images/?q=panda").json()["count"] == 1
    assert client.get(ADMIN + f"images/{imported.pk}/").status_code == 200
    items = client.get(ADMIN + f"imports/{batch.pk}/").json()
    assert items["results"][0]["image"]["id"] == str(imported.pk)
    assert items["results"][0]["image"]["status"] == "pending"
    assert client.get(ADMIN + "player-submissions/?status=all").json()["count"] == 1
    with patch("moderation.administration_views.health", return_value=[]):
        metrics = client.get(ADMIN).json()
    assert metrics["pending_images"] == 26 and metrics["pending_player_submissions"] == 1
    assert metrics["incomplete_imports"] == 1 and metrics["playable_images"] == 0
    assert review(client, administrator, contribution, "approve").status_code == 200
    with patch("moderation.administration_views.health", return_value=[]):
        metrics = client.get(ADMIN).json()
    assert metrics["playable_images"] == 1 and metrics["pending_player_submissions"] == 0
    assert client.get(ADMIN + "images/").json()["count"] == 27
    imported.refresh_from_db()
    assert imported.status == "pending" and not imported.player_contribution


def test_rejected_player_deletion_remains_available_outside_library(
    client, administrator, contribution, django_capture_on_commit_callbacks
):
    assert review(client, administrator, contribution, "reject").status_code == 200
    assert client.get(ADMIN + "images/").json()["count"] == 0
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            ADMIN + f"images/{contribution.pk}/delete/", {"confirm": True}, format="json"
        )
    assert response.status_code == 200
    removed = client.get(ADMIN + "player-submissions/?status=removed").json()
    assert removed["count"] == 1 and removed["results"][0]["id"] == str(contribution.pk)
    assert "canonical_answer" not in removed["results"][0]
    assert not ImageSubmission.objects.exists() and RemovedContribution.objects.count() == 1


@pytest.mark.parametrize("role", ["guest", "player", "moderator", "partial_admin"])
def test_only_administrators_can_review_or_remove(client, user, administrator, contribution, role):
    actor = user
    if role == "moderator":
        change_access(administrator, user.pk, True)
    if role == "partial_admin":
        user.is_staff = True
        user.save()
    client.force_authenticate(None if role == "guest" else actor)
    assert client.get(ADMIN + "player-submissions/").status_code == 403
    for op in ["approve", "reject", "remove"]:
        assert (
            client.post(
                ADMIN + f"player-submissions/{contribution.pk}/review/",
                {"operation": op, "confirm": True},
                format="json",
            ).status_code
            == 403
        )
    assert ImageSubmission.objects.filter(pk=contribution.pk, status="pending").exists()


def test_remove_creates_content_free_receipt_deletes_bytes_and_invalidates_urls(
    client, user, administrator, contribution, django_capture_on_commit_callbacks
):
    stored = contribution.image_file.name
    assert review(client, administrator, contribution, "remove").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        response = review(client, administrator, contribution, "remove", confirm=True)
    assert response.status_code == 200
    assert not ImageSubmission.objects.filter(pk=contribution.pk).exists()
    receipt = RemovedContribution.objects.get(pk=contribution.pk)
    assert receipt.submitted_by_id == user.pk and receipt.created_at == contribution.created_at
    assert not contribution.image_file.storage.exists(stored)
    assert review(client, administrator, contribution, "remove", confirm=True).status_code == 200
    assert RemovedContribution.objects.count() == 1
    client.force_authenticate(user)
    detail = client.get(ROOT + f"{contribution.pk}/").json()
    assert set(detail) == {"id", "status", "created_at"} and detail["status"] == "removed"
    assert client.get(ROOT + f"{contribution.pk}/preview/").status_code == 404
    client.force_authenticate(administrator)
    assert client.get(f"/api/library/submissions/{contribution.pk}/preview/").status_code == 404
    assert client.get(ADMIN + f"images/{contribution.pk}/preview/").status_code == 404


@pytest.mark.parametrize("retired", [False, True])
def test_library_delete_also_leaves_receipt_and_preserves_games_without_removed_content(
    client, user, administrator, contribution, retired, django_capture_on_commit_callbacks
):
    assert (
        review(client, administrator, contribution, "approve" if retired else "reject").status_code
        == 200
    )
    if retired:
        contribution.refresh_from_db()
        contribution.retired_at = timezone.now()
        contribution.save()
    match = Match.objects.create(mode="singleplayer", status="complete")
    participant = Participant.objects.create(match=match, user=user, total_score=750)
    game_round = Round.objects.create(
        match=match,
        image=contribution,
        number=1,
        answer_snapshot="Removed answer",
        synonyms_snapshot=["Bad synonym"],
        image_storage_name=contribution.image_file.name,
        ended_at=timezone.now(),
        outcome="solved",
        winner=participant,
        is_decisive=True,
    )
    guess = Guess.objects.create(
        round=game_round, participant=participant, text="Removed answer", sequence=1, correct=True
    )
    with django_capture_on_commit_callbacks(execute=True):
        delete_library_image(administrator, contribution.pk, True)
    assert RemovedContribution.objects.filter(pk=contribution.pk).exists()
    game_round.refresh_from_db()
    guess.refresh_from_db()
    participant.refresh_from_db()
    assert game_round.answer_snapshot == "Removed image" and not game_round.synonyms_snapshot
    assert game_round.image_id is None and not game_round.image_storage_name
    assert guess.text == "[Removed image]" and guess.correct and participant.total_score == 750
    assert Match.objects.filter(pk=match.pk).exists() and game_round.winner_id == participant.pk


def test_admin_imports_do_not_enter_inbox_and_origin_survives_account_erasure(
    client, user, administrator, contribution
):
    ImageSubmission.objects.create(
        submitted_by=administrator,
        category=contribution.category,
        canonical_answer="Admin import",
        source="manual",
        external_image_url="https://example.test/import",
        license="CC0",
        attribution="Credit",
    )
    assert review(client, administrator, contribution, "approve").status_code == 200
    issue(administrator, user.pk, {"kind": "closed", "category": "other"})
    delete_account(
        administrator,
        user.pk,
        {
            "current_password": "Contribution-password-734!",
            "confirmation": user.username,
            "reason": "Synthetic deletion",
        },
    )
    contribution.refresh_from_db()
    assert (
        contribution.player_contribution
        and contribution.submitted_by_id is None
        and contribution.status == "approved"
    )
    assert contribution.attribution and contribution.license
    response = client.get(ADMIN + "player-submissions/?status=all")
    assert response.status_code == 200 and response.json()["count"] == 1
    assert response.json()["results"][0]["submitter_id"] is None


def test_account_erasure_removes_receipts(client, user, administrator, contribution):
    assert review(client, administrator, contribution, "remove", confirm=True).status_code == 200
    issue(administrator, user.pk, {"kind": "closed", "category": "other"})
    delete_account(
        administrator,
        user.pk,
        {
            "current_password": "Contribution-password-734!",
            "confirmation": user.username,
            "reason": "Synthetic deletion",
        },
    )
    assert not RemovedContribution.objects.exists()


def test_removal_cleanup_failure_can_be_retried(
    client, administrator, contribution, django_capture_on_commit_callbacks
):
    with patch(
        "library.file_cleanup.default_storage.delete", side_effect=OSError("private storage failed")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                review(client, administrator, contribution, "remove", confirm=True).status_code
                == 200
            )
    job = PendingFileDeletion.objects.get()
    assert job.attempts == 1 and not job.completed_at
    call_command("cleanup_deleted_files", stdout=StringIO())
    job.refresh_from_db()
    assert job.completed_at and not contribution.image_file.storage.exists(
        contribution.image_file.name
    )


def test_upload_rollback_has_durable_file_cleanup(
    user, uploaded_submission, django_capture_on_commit_callbacks
):
    body = uploaded_submission()
    body["accepted_synonyms"] = []
    serializer = ContributionInput(data=body)
    serializer.is_valid(raise_exception=True)
    with patch(
        "library.contributions.ImageSubmission.save", side_effect=RuntimeError("failed write")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError):
                create_contribution(user, serializer.validated_data)
    assert not ImageSubmission.objects.exists()
    job = PendingFileDeletion.objects.get()
    assert job.completed_at


def test_legacy_external_records_and_origin_backfill_preserve_imports(
    user, administrator, submission_data
):
    serializer = SubmissionSerializer(data=submission_data)
    serializer.is_valid(raise_exception=True)
    legacy = serializer.save(submitted_by=user)
    serializer = SubmissionSerializer(data={**submission_data, "canonical_answer": "Imported"})
    serializer.is_valid(raise_exception=True)
    imported = serializer.save(submitted_by=user)
    batch = ImportBatch.objects.create(created_by=administrator, name="Import")
    ImportItem.objects.create(
        batch=batch,
        image=imported,
        request_id=uuid.uuid4(),
        filename="private.jpg",
        status="uploaded",
    )
    module = importlib.import_module("library.migrations.0007_contributions")
    module.identify_existing_player_contributions(apps, SimpleNamespace(connection=connection))
    legacy.refresh_from_db()
    imported.refresh_from_db()
    assert legacy.player_contribution and not imported.player_contribution
    assert (
        legacy.external_image_url == submission_data["external_image_url"] and not legacy.image_file
    )


def test_new_upload_rate_limit(client, user, uploaded_submission):
    client.force_authenticate(user)
    for index in range(21):
        response = client.post(ROOT, uploaded_submission(), format="multipart")
        assert response.status_code == (201 if index < 20 else 429)
    assert ImageSubmission.objects.count() == 20


def test_new_endpoints_require_real_session_csrf(
    user, administrator, contribution, uploaded_submission
):
    browser = APIClient(enforce_csrf_checks=True)
    browser.force_login(user, backend="accounts.backends.AccountBackend")
    assert browser.post(ROOT, uploaded_submission(), format="multipart").status_code == 403
    browser.force_login(administrator, backend="accounts.backends.AccountBackend")
    assert (
        browser.post(
            ADMIN + f"player-submissions/{contribution.pk}/review/",
            {"operation": "approve"},
            format="json",
        ).status_code
        == 403
    )
