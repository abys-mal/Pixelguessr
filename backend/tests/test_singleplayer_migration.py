import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_legacy_games_are_preserved_by_additive_migration():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [
        ("games", "0002_guess_request_id_round_answer_snapshot_and_more"),
        ("accounts", "0001_initial"),
    ]
    try:
        executor.migrate(previous)
        apps = executor.loader.project_state(previous).apps
        User = apps.get_model("accounts", "User")
        Image = apps.get_model("library", "ImageSubmission")
        Category = apps.get_model("library", "Category")
        Match = apps.get_model("games", "Match")
        Participant = apps.get_model("games", "Participant")
        Round = apps.get_model("games", "Round")
        State = apps.get_model("games", "RoundPlayerState")
        user = User.objects.create(username="legacy", email="legacy@example.com", password="!")
        staff = User.objects.create(
            username="legacy-staff", email="legacy-staff@example.com", password="!", is_staff=True
        )
        now = timezone.now()
        image = Image.objects.create(
            submitted_by=user,
            category=Category.objects.first(),
            canonical_answer="legacy answer",
            accepted_synonyms=["legacy synonym"],
            source="manual",
            image_file="images/private-legacy.webp",
            license="CC0",
            attribution="Original",
            status="approved",
            reviewed_by=staff,
            reviewed_at=now,
        )
        match = Match.objects.create(mode="singleplayer", status="complete", completed_at=now)
        participant = Participant.objects.create(match=match, user=user, total_score=17)
        old = Round.objects.create(
            match=match,
            image=image,
            number=1,
            start_request_id=uuid.uuid4(),
            reveal_duration_seconds=30,
            reveal_order=list(range(400)),
            reveal_started_at=now - timedelta(seconds=12),
            ended_at=now,
            winner=participant,
            expires_at=now + timedelta(days=1),
            answer_snapshot="legacy answer",
            synonyms_snapshot=["legacy synonym"],
            image_storage_name=image.image_file.name,
        )
        State.objects.create(round=old, participant=participant, score=17)
        active_match = Match.objects.create(mode="singleplayer", status="active")
        active = Round.objects.create(
            match=active_match,
            image=image,
            number=1,
            reveal_started_at=now,
            reveal_duration_seconds=30,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        apps = executor.loader.project_state(latest).apps
        new_round = apps.get_model("games", "Round")
        restored = new_round.objects.get(pk=old.pk)
        assert restored.outcome == "solved" and restored.reveal_duration_seconds == 30
        assert restored.reveal_started_at == old.reveal_started_at and restored.ended_at == now
        assert (
            restored.answer_snapshot == old.answer_snapshot
            and restored.synonyms_snapshot == old.synonyms_snapshot
        )
        assert (
            restored.image_id == image.pk and restored.image_storage_name == image.image_file.name
        )
        assert restored.match.singleplayer_round_limit == 1 and restored.match.status == "complete"
        assert (
            restored.player_states.get().score == 17
            and restored.match.participants.get().total_score == 17
        )
        assert new_round.objects.get(pk=active.pk).match.status == "active"
        assert new_round.objects.count() == 2
        assert (
            apps.get_model("library", "ImageSubmission").objects.get(pk=image.pk).status
            == "approved"
        )
    finally:
        MigrationExecutor(connection).migrate(latest)
