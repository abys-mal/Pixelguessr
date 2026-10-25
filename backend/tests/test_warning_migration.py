from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_warning_expiry_migration_preserves_inactive_history_and_rebases_live_warnings():
    executor = MigrationExecutor(connection)
    after = executor.loader.graph.leaf_nodes()
    before = [node for node in after if node[0] != "moderation"] + [
        ("moderation", "0007_ipaccessentry")
    ]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    User, Sanction = old.get_model("accounts", "User"), old.get_model("moderation", "Sanction")
    user = User.objects.create(username="migration_player", email="migration-player@example.test")
    actor = User.objects.create(username="migration_actor", email="migration-actor@example.test")
    now = timezone.now()

    def create(**kwargs):
        return Sanction.objects.create(
            user_id=user.pk,
            issued_by_id=actor.pk,
            kind="warning",
            category="other",
            reason="Preserve history",
            **kwargs,
        )

    live = create(starts_at=now - timedelta(days=10), expires_at=now + timedelta(days=80))
    acknowledged = create(
        starts_at=now - timedelta(days=40),
        acknowledged_at=now - timedelta(days=5),
        expires_at=now + timedelta(days=50),
    )
    expired = create(starts_at=now - timedelta(days=100), expires_at=now - timedelta(days=10))
    reversed = create(
        starts_at=now - timedelta(days=2),
        expires_at=now + timedelta(days=88),
        revoked_at=now - timedelta(days=1),
        revoked_by_id=actor.pk,
    )
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        current = executor.loader.project_state(after).apps.get_model("moderation", "Sanction")
        assert current.objects.get(pk=live.pk).expires_at is None
        assert current.objects.get(
            pk=acknowledged.pk
        ).expires_at == acknowledged.acknowledged_at + timedelta(days=90)
        assert current.objects.get(pk=expired.pk).expires_at == expired.expires_at
        restored = current.objects.get(pk=reversed.pk)
        assert (
            restored.revoked_at == reversed.revoked_at
            and restored.expires_at == reversed.expires_at
        )
        assert current.objects.count() == 4
    finally:
        MigrationExecutor(connection).migrate(after)
