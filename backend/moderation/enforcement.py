"""Reconcile committed sanctions with durable gameplay; clocks and reads also recover it."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from .services import account_restrictions


def account_group(user_id):
    return f"account.{user_id}"


def publish_account(user_id):
    async_to_sync(get_channel_layer().group_send)(
        account_group(user_id), {"type": "account.changed"}
    )


def schedule(user_id):
    transaction.on_commit(lambda: publish_account(user_id), robust=True)


def enforce_user(user_id):
    from games import ranked

    with transaction.atomic():
        ranked.gate()
        enforce_locked(user_id)
    publish_account(user_id)


def enforce_locked(user_id):
    """Sanction writers take ranked gate -> user -> party, matching gameplay lock ordering."""
    from games import parties, ranked
    from games.models import Match, Party

    ranked.enforce_queue(user_id)
    for match in Match.objects.filter(
        mode="ranked", status="active", participants__user_id=user_id
    ):
        ranked.reconcile(match, timezone.now())
    for code in Party.objects.filter(
        members__user_id=user_id, members__left_at__isnull=True
    ).values_list("code", flat=True):
        with transaction.atomic():
            party = parties.lock_party(code, allow_closed=True)
            enforce_party(party, timezone.now())


def enforce_party(party, now):
    """Called only under the existing party writer lock; never takes a user/ranked lock."""
    from games import parties
    from games.models import Party, Round

    if party.status in (Party.Status.ABORTED, Party.Status.CLOSED):
        return
    members = list(party.members.filter(left_at__isnull=True).select_related("user"))
    restricted = []
    for member in members:
        if member.user_id:
            restrictions = account_restrictions(member.user)
            if restrictions["blocked"] or restrictions["suspension"]:
                restricted.append((member, "closed" if restrictions["blocked"] else "suspended"))
    host = next(((m, reason) for m, reason in restricted if m.pk == party.host_id), None)
    if host:
        parties.end_party(party, f"host_{host[1]}", now)
        party.members.filter(left_at__isnull=True).update(
            left_at=now, departure_reason="host_ended"
        )
        if party.current_match_id:
            Round.objects.filter(
                match_id=party.current_match_id,
                reveal_started_at__isnull=False,
                ended_at__isnull=True,
            ).update(ended_at=now, outcome=Round.Outcome.EXPIRED)
        parties.changed(party)
        return
    for member, reason in restricted:
        member.left_at = now
        member.departure_reason = reason
        member.save(update_fields=["left_at", "departure_reason"])
    if restricted:
        parties.changed(party)
