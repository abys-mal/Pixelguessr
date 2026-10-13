"""Durable ranked decisions, serialized before mutable reads on SQLite/PostgreSQL.

The singleton writer gate intentionally favors correctness over matchmaking throughput.
No essential state or disconnect timestamp depends on process-local memory.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from accounts.models import User
from moderation.services import account_restrictions

from .models import (
    Match,
    Participant,
    RankedConnection,
    RankedGate,
    RankedQueue,
    Round,
    RoundPlayerState,
)
from .ranked_rules import elo_after, rule, search_window, tier
from .reveal import prepare_image
from .services import (
    GameError,
    approved_images,
    choose_image,
    image_fields,
    normalize_guess,
    revealed_count,
)


def gate():
    # Acquire the durable writer lock before reading mutable ranked state.
    if not RankedGate.objects.filter(pk=1).update(revision=F("revision") + 1):
        RankedGate.objects.get_or_create(pk=1)
        RankedGate.objects.filter(pk=1).update(revision=F("revision") + 1)


def eligible(user):
    if not user or not user.is_authenticated:
        raise PermissionDenied("Sign in to play Ranked Duel.")
    restrictions = account_restrictions(user)
    if (
        restrictions["blocked"]
        or restrictions["probation"]
        or restrictions["unacknowledged_warnings"]
    ):
        raise PermissionDenied("Resolve your account notice before playing Ranked Duel.")


def owned(user, match_id):
    eligible(user)
    match = Match.objects.filter(
        pk=match_id, mode=Match.Mode.RANKED, participants__user=user
    ).first()
    if not match:
        raise NotFound("This Ranked Duel is unavailable.")
    return match


def participants(match):
    return list(match.participants.select_related("user").order_by("joined_at", "id"))


def current_round(match):
    return match.rounds.select_related("image__category").order_by("number").last()


def changed(match):
    match.ranked_revision += 1
    match.save()


def new_round(match, now, countdown=False):
    images = approved_images()
    used = list(match.rounds.order_by("number").values_list("image_id", flat=True))
    image = choose_image(images, used, used[-1] if used else None)
    prepare_image(image.image_file.name)
    order = list(range(settings.SINGLEPLAYER_GRID_SIZE**2))
    secrets.SystemRandom().shuffle(order)
    game_round = Round.objects.create(
        match=match,
        number=len(used) + 1,
        grid_size=settings.SINGLEPLAYER_GRID_SIZE,
        reveal_duration_seconds=rule("reveal_seconds"),
        reveal_order=order,
        reveal_started_at=now + timedelta(seconds=rule("countdown_seconds") if countdown else 0),
        **image_fields(image),
    )
    for player in match.participants.all():
        RoundPlayerState.objects.create(round=game_round, participant=player)
    match.ranked_message = ""
    changed(match)
    return game_round


def complete(match, winner, outcome, now):
    if match.status != Match.Status.ACTIVE:
        return
    match.status = Match.Status.COMPLETE
    match.completed_at = now
    match.ranked_winner = winner
    match.ranked_outcome = outcome
    if winner:
        for player in sorted(participants(match), key=lambda p: str(p.user_id)):
            opponent = next(p for p in participants(match) if p.pk != player.pk)
            player.rating_after = elo_after(
                player.rating_before,
                opponent.rating_before,
                player.pk == winner.pk,
                player.rated_matches_before,
            )
            player.rating_delta = player.rating_after - player.rating_before
            player.save(update_fields=["rating_after", "rating_delta"])
            User.objects.filter(pk=player.user_id).update(
                rating=player.rating_after,
                ranked_matches=F("ranked_matches") + 1,
                ranked_wins=F("ranked_wins") + int(player.pk == winner.pk),
                ranked_losses=F("ranked_losses") + int(player.pk != winner.pk),
            )
        match.elo_applied_at = now
    else:
        for player in participants(match):
            player.rating_after = player.rating_before
            player.rating_delta = 0
            player.save(update_fields=["rating_after", "rating_delta"])
    changed(match)


def finish_round(match, game_round, winner, now):
    if game_round.ended_at or match.status != Match.Status.ACTIVE:
        return
    game_round.ended_at = now
    game_round.outcome = Round.Outcome.COMPLETE
    game_round.winner = winner
    game_round.is_decisive = winner is not None
    game_round.save(update_fields=["ended_at", "outcome", "winner", "is_decisive"])
    if winner:
        winner.decisive_wins += 1
        winner.save(update_fields=["decisive_wins"])
        if winner.decisive_wins >= rule("wins_to_finish"):
            complete(match, winner, "victory", now)
    changed(match)


def connected(player, now):
    return (
        player.ranked_disconnected_at is None
        and player.ranked_last_seen is not None
        and (now - player.ranked_last_seen).total_seconds() <= rule("presence_seconds")
    )


def reconcile(match, now):
    if match.status != Match.Status.ACTIVE:
        return
    players = participants(match)
    cutoff = now - timedelta(seconds=rule("presence_seconds"))
    RankedConnection.objects.filter(match=match, last_seen__lt=cutoff).delete()
    for player in players:
        if player.ranked_disconnected_at is None and player.ranked_last_seen < cutoff:
            if not RankedConnection.objects.filter(match=match, user_id=player.user_id).exists():
                # Missing heartbeat/server crash: infer from the last durable lease expiry.
                player.ranked_disconnected_at = player.ranked_last_seen + timedelta(
                    seconds=rule("presence_seconds")
                )
                player.save(update_fields=["ranked_disconnected_at"])
                changed(match)
    absent = [p for p in players if p.ranked_disconnected_at is not None]
    grace = timedelta(seconds=rule("grace_seconds"))
    coincident = len(absent) == 2 and abs(
        (absent[0].ranked_disconnected_at - absent[1].ranked_disconnected_at).total_seconds()
    ) <= rule("coincidence_seconds")
    if coincident:
        if all(now >= p.ranked_disconnected_at + grace for p in absent):
            complete(match, None, "no_contest", now)
            return
    else:
        expired = sorted(
            (p for p in absent if now >= p.ranked_disconnected_at + grace),
            key=lambda p: (p.ranked_disconnected_at, str(p.pk)),
        )
        if expired:
            complete(match, next(p for p in players if p.pk != expired[0].pk), "forfeit", now)
            return
    game_round = current_round(match)
    deadline = game_round.reveal_started_at + timedelta(seconds=game_round.reveal_duration_seconds)
    if not game_round.ended_at and now >= deadline:
        finish_round(match, game_round, None, deadline)
    if game_round.ended_at and now >= game_round.ended_at + timedelta(
        seconds=rule("results_seconds")
    ):
        if not all(connected(p, now) for p in players):
            return
        try:
            # Resume at now, never create a chain of unseen rounds after downtime.
            new_round(match, now)
        except GameError as exc:
            message = str(exc.detail["detail"])
            if match.ranked_message != message:
                match.ranked_message = message
                changed(match)


def queue_payload(entry, now):
    if entry.match_id and entry.match.status == Match.Status.ACTIVE:
        return {
            "status": "matched",
            "match_id": str(entry.match_id),
            "ticket": str(entry.ticket),
            "server_now": now.isoformat(),
        }
    waiting = entry.queued_at is not None
    return {
        "status": "searching" if waiting else "idle",
        "match_id": None,
        "ticket": str(entry.ticket) if entry.ticket else None,
        "queued_at": entry.queued_at.isoformat() if waiting else None,
        "server_now": now.isoformat(),
        "search_window": search_window(max(0, (now - entry.queued_at).total_seconds()))
        if waiting
        else None,
        "rating": entry.user.rating,
        "tier": tier(entry.user.rating),
    }


def matchmake(now):
    cutoff = now - timedelta(seconds=rule("presence_seconds"))
    RankedQueue.objects.filter(queued_at__isnull=False, last_seen__lt=cutoff).update(queued_at=None)
    entries = list(
        RankedQueue.objects.filter(queued_at__isnull=False)
        .select_related("user")
        .order_by("queued_at", "user_id")
    )
    available = []
    for entry in entries:
        try:
            eligible(entry.user)
        except PermissionDenied:
            entry.queued_at = None
            entry.save(update_fields=["queued_at"])
            continue
        available.append(entry)
    while available:
        first = available.pop(0)
        limit = search_window((now - first.queued_at).total_seconds())
        candidates = [
            entry
            for entry in available
            if abs(entry.rating_snapshot - first.rating_snapshot)
            <= min(limit, search_window((now - entry.queued_at).total_seconds()))
        ]
        if not candidates:
            continue
        second = min(
            candidates,
            key=lambda entry: (
                abs(entry.rating_snapshot - first.rating_snapshot),
                entry.queued_at,
                str(entry.user_id),
            ),
        )
        available.remove(second)
        try:
            # A savepoint leaves queued users intact if library/storage is unavailable.
            with transaction.atomic():
                match = Match.objects.create(mode=Match.Mode.RANKED, status=Match.Status.ACTIVE)
                for entry in (first, second):
                    Participant.objects.create(
                        match=match,
                        user=entry.user,
                        rating_before=entry.user.rating,
                        rated_matches_before=entry.user.ranked_matches,
                        ranked_last_seen=now,
                    )
                new_round(match, now, countdown=True)
                for entry in (first, second):
                    entry.match = match
                    entry.queued_at = None
                    entry.save(update_fields=["match", "queued_at"])
        except GameError:
            # Queue POST validates the library too; clock retries a later recovery.
            return


def queue_join(user, ticket):
    eligible(user)
    with transaction.atomic():
        gate()
        now = timezone.now()
        entry, _ = RankedQueue.objects.get_or_create(user=user)
        if entry.match_id and entry.match.status == Match.Status.ACTIVE:
            raise GameError("Resume your current Ranked Duel first.", "match_in_progress")
        if entry.queued_at and entry.last_seen >= now - timedelta(seconds=rule("presence_seconds")):
            raise GameError("You are already searching for an opponent.", "already_queued")
        if entry.ticket == ticket:
            raise GameError("This search has ended. Start a new search.", "stale_queue")
        if RankedQueue.objects.filter(ticket=ticket).exclude(user=user).exists():
            raise GameError("This search request was already used.", "request_conflict")
        approved_images()
        entry.ticket = ticket
        entry.queued_at = now
        entry.last_seen = now
        entry.rating_snapshot = User.objects.get(pk=user.pk).rating
        entry.match = None
        entry.save()
        matchmake(now)
        return queue_payload(
            RankedQueue.objects.select_related("match", "user").get(pk=user.pk), now
        )


def queue_state(user, ticket=None, heartbeat=False, cancel=False, connection_id=None):
    eligible(user)
    with transaction.atomic():
        gate()
        now = timezone.now()
        entry = RankedQueue.objects.select_related("match", "user").filter(pk=user.pk).first()
        if not entry:
            return {
                "status": "idle",
                "match_id": None,
                "ticket": None,
                "server_now": now.isoformat(),
            }
        if ticket and entry.ticket != ticket:
            raise GameError("This search is no longer current.", "stale_queue")
        if cancel and entry.queued_at:
            entry.queued_at = None
            entry.save(update_fields=["queued_at"])
        elif heartbeat and entry.queued_at:
            if entry.last_seen < now - timedelta(seconds=rule("presence_seconds")):
                entry.queued_at = None
                entry.save(update_fields=["queued_at"])
            else:
                entry.last_seen = now
                entry.save(update_fields=["last_seen"])
        if connection_id and heartbeat:
            RankedConnection.objects.filter(pk=connection_id).update(last_seen=now)
        matchmake(now)
        return queue_payload(
            RankedQueue.objects.select_related("match", "user").get(pk=user.pk), now
        )


def queue_connect(user, ticket, connection_id):
    state = queue_state(user, ticket, heartbeat=True)
    if state["status"] == "searching":
        with transaction.atomic():
            gate()
            entry = RankedQueue.objects.get(pk=user.pk)
            if entry.ticket == ticket and entry.queued_at:
                RankedConnection.objects.create(
                    id=connection_id, user=user, queue_ticket=ticket, last_seen=timezone.now()
                )
    return state


def disconnect(connection_id):
    with transaction.atomic():
        gate()
        now = timezone.now()
        connection = RankedConnection.objects.filter(pk=connection_id).first()
        if not connection:
            return
        connection.delete()
        cutoff = now - timedelta(seconds=rule("presence_seconds"))
        if connection.match_id:
            if not RankedConnection.objects.filter(
                match_id=connection.match_id, user_id=connection.user_id, last_seen__gte=cutoff
            ).exists():
                match = Match.objects.get(pk=connection.match_id)
                if match.status == Match.Status.ACTIVE:
                    player = match.participants.get(user_id=connection.user_id)
                    if player.ranked_disconnected_at is None:
                        player.ranked_disconnected_at = now
                        player.save(update_fields=["ranked_disconnected_at"])
                        changed(match)
                    reconcile(match, now)
        elif not RankedConnection.objects.filter(
            user_id=connection.user_id, queue_ticket=connection.queue_ticket, last_seen__gte=cutoff
        ).exists():
            RankedQueue.objects.filter(
                user_id=connection.user_id, ticket=connection.queue_ticket, queued_at__isnull=False
            ).update(queued_at=None)


def transition_due(match, players, game_round, now):
    """Only durable deadlines can require a writer; reveal progress is read-only."""
    if match.status != Match.Status.ACTIVE:
        return False
    cutoff = now - timedelta(seconds=rule("presence_seconds"))
    if any(p.ranked_disconnected_at is None and p.ranked_last_seen < cutoff for p in players):
        return True
    absent = [p for p in players if p.ranked_disconnected_at is not None]
    grace = timedelta(seconds=rule("grace_seconds"))
    coincident = len(absent) == 2 and abs(
        (absent[0].ranked_disconnected_at - absent[1].ranked_disconnected_at).total_seconds()
    ) <= rule("coincidence_seconds")
    expired = [now >= p.ranked_disconnected_at + grace for p in absent]
    if expired and (all(expired) if coincident else any(expired)):
        return True
    if not game_round:
        return False
    if not game_round.ended_at:
        return now >= game_round.reveal_started_at + timedelta(
            seconds=game_round.reveal_duration_seconds
        )
    return now >= game_round.ended_at + timedelta(seconds=rule("results_seconds")) and all(
        connected(p, now) for p in players
    )


def read_snapshot(user, match_id, *, include_states=True):
    """Read persisted state without a writer gate when no transition is due.

    SQLite's read transaction gives a consistent snapshot. PostgreSQL READ COMMITTED
    may see a concurrent guess between SELECTs: recheck the durable match revision
    after loading relations, retry, then fall back to the existing serialized path.
    Nothing essential is cached in the process or inferred from a browser clock.
    """
    for _ in range(3):
        with transaction.atomic():
            match = owned(user, match_id)
            players = participants(match)
            game_round = current_round(match)
            states = list(game_round.player_states.all()) if include_states and game_round else []
            revision = (
                Match.objects.filter(pk=match.pk).values_list("ranked_revision", flat=True).first()
            )
            if revision != match.ranked_revision:
                continue
            now = timezone.now()
            if transition_due(match, players, game_round, now):
                return None
            return match, players, game_round, states, now
    return None


def state(user, match_id, *, connection_id=None, heartbeat=False):
    if not heartbeat:
        snapshot = read_snapshot(user, match_id)
        if snapshot:
            match, players, game_round, states, now = snapshot
            return payload(match, user, now, snapshot=(players, game_round, states))
    # Exit the read transaction before taking the writer gate (no SQLite lock upgrade).
    error = None
    result = None
    with transaction.atomic():
        gate()
        match = owned(user, match_id)
        now = timezone.now()
        reconcile(match, now)
        player = match.participants.get(user=user)
        if heartbeat and match.status == Match.Status.ACTIVE:
            if player.ranked_disconnected_at and now >= player.ranked_disconnected_at + timedelta(
                seconds=rule("grace_seconds")
            ):
                error = GameError(
                    "Your reconnection grace period expired.", "reconnect_expired", 403
                )
            else:
                player.ranked_last_seen = now
                if player.ranked_disconnected_at:
                    player.ranked_disconnected_at = None
                    changed(match)
                player.save(update_fields=["ranked_last_seen", "ranked_disconnected_at"])
                if connection_id:
                    RankedConnection.objects.update_or_create(
                        pk=connection_id, defaults={"user": user, "match": match, "last_seen": now}
                    )
                reconcile(match, now)
        result = payload(match, user, now)
    if error:
        raise error
    return result


def submit(user, match_id, round_id, text, request_id):
    error = None
    result = None
    with transaction.atomic():
        gate()
        match = owned(user, match_id)
        now = timezone.now()
        reconcile(match, now)
        try:
            if match.status != Match.Status.ACTIVE:
                raise GameError("This match has finished.", "match_complete")
            game_round = current_round(match)
            if game_round.pk != round_id or game_round.ended_at:
                raise GameError("This round has ended.", "round_ended")
            if now < game_round.reveal_started_at:
                raise GameError("Wait for the round to begin.", "round_not_started")
            player = match.participants.get(user=user)
            if player.ranked_disconnected_at and now >= player.ranked_disconnected_at + timedelta(
                seconds=rule("grace_seconds")
            ):
                raise GameError("Your reconnection grace period expired.", "reconnect_expired", 403)
            player_state = RoundPlayerState.objects.get(round=game_round, participant=player)
            if player_state.ranked_guessed_at:
                raise GameError("You already used your guess for this round.", "guess_used")
            if RoundPlayerState.objects.filter(ranked_request_id=request_id).exists():
                raise GameError("This guess request was already used.", "request_conflict")
            correct = normalize_guess(text) in {
                normalize_guess(value)
                for value in [game_round.answer_snapshot, *game_round.synonyms_snapshot]
            }
            player_state.ranked_guessed_at = now
            player_state.ranked_request_id = request_id
            if correct:
                player_state.solved_at = now
            player_state.save(update_fields=["ranked_guessed_at", "ranked_request_id", "solved_at"])
            # Ranked never stores the submitted text or a lifetime image-exposure log.
            if correct:
                finish_round(match, game_round, player, now)
            elif not game_round.player_states.filter(ranked_guessed_at__isnull=True).exists():
                finish_round(match, game_round, None, now)
            changed(match)
            result = "correct" if correct else "incorrect"
        except APIException as exc:
            error = exc
        response = {"state": payload(match, user, now), "result": result}
    if error:
        raise error
    return response


def leave(user, match_id):
    with transaction.atomic():
        gate()
        match = owned(user, match_id)
        if match.status == Match.Status.ACTIVE:
            complete(match, match.participants.exclude(user=user).get(), "forfeit", timezone.now())
        return payload(match, user, timezone.now())


def reveal_count(game_round, now):
    # Shared 250ms timeline frames; never grant pixels ahead of the live server clock.
    elapsed = max(0, (now - game_round.reveal_started_at).total_seconds())
    frame_time = game_round.reveal_started_at + timedelta(seconds=int(elapsed * 4) / 4)
    return revealed_count(game_round, frame_time)


def payload(match, user, now, *, snapshot=None):
    if snapshot is None:
        players = participants(match)
        game_round = current_round(match)
        states = list(game_round.player_states.all()) if game_round else []
    else:
        players, game_round, states = snapshot
    result = {
        "id": str(match.pk),
        "status": match.status,
        "revision": match.ranked_revision,
        "server_now": now.isoformat(),
        "me_id": str(next(p.pk for p in players if p.user_id == user.pk)),
        "winner_id": str(match.ranked_winner_id) if match.ranked_winner_id else None,
        "outcome": match.ranked_outcome,
        "message": match.ranked_message,
        "players": [
            {
                "id": str(p.pk),
                "username": p.user.username,
                "rating_before": p.rating_before,
                "rating_after": p.rating_after,
                "rating_delta": p.rating_delta,
                "tier": tier(p.rating_after if p.rating_after is not None else p.rating_before),
                "wins": p.decisive_wins,
                "connected": connected(p, now),
                "reconnect_until": (
                    p.ranked_disconnected_at + timedelta(seconds=rule("grace_seconds"))
                ).isoformat()
                if p.ranked_disconnected_at
                else None,
            }
            for p in players
        ],
        "round": None,
        "waiting": False,
    }
    if not game_round:
        return result
    completed = game_round.ended_at is not None
    count = game_round.grid_size**2 if completed else reveal_count(game_round, now)
    deadline = game_round.reveal_started_at + timedelta(seconds=game_round.reveal_duration_seconds)
    result["round"] = {
        "id": str(game_round.pk),
        "number": game_round.number,
        "status": "results"
        if completed
        else "countdown"
        if now < game_round.reveal_started_at
        else "active",
        "started_at": game_round.reveal_started_at.isoformat(),
        "reveal_finishes_at": deadline.isoformat(),
        "next_starts_at": (
            game_round.ended_at + timedelta(seconds=rule("results_seconds"))
        ).isoformat()
        if completed
        else None,
        "winner_id": str(game_round.winner_id) if game_round.winner_id else None,
        "grid_size": game_round.grid_size,
        "revealed_tiles": game_round.reveal_order[:count],
        "revealed_count": count,
        "total_tiles": game_round.grid_size**2,
        "image_url": f"/api/ranked/matches/{match.pk}/rounds/{game_round.pk}/image/?v={count}",
        "guessed_ids": [str(s.participant_id) for s in states if s.ranked_guessed_at],
        "completion": {
            "answer": game_round.answer_snapshot,
            "license": game_round.image.license,
            "attribution": game_round.image.attribution,
        }
        if completed
        else None,
    }
    result["waiting"] = (
        completed
        and match.status == Match.Status.ACTIVE
        and not all(connected(p, now) for p in players)
    )
    # Forfeits/no-contests cannot newly disclose an unfinished image/answer.
    if match.status == Match.Status.COMPLETE and not completed:
        result["round"] = None
    return result


def image(user, match_id, round_id):
    snapshot = read_snapshot(user, match_id, include_states=False)
    if snapshot:
        match, _, game_round, _, now = snapshot
    else:
        # Commit due transitions even when the requested image is later refused.
        state(user, match_id)
        with transaction.atomic():
            gate()
            match = owned(user, match_id)
            game_round = current_round(match)
            now = timezone.now()
    if (
        not game_round
        or game_round.pk != round_id
        or (match.status == Match.Status.COMPLETE and not game_round.ended_at)
    ):
        raise NotFound("This ranked image is unavailable.")
    return (
        game_round,
        now,
        game_round.grid_size**2 if game_round.ended_at else reveal_count(game_round, now),
    )


def clock_tick():
    with transaction.atomic():
        gate()
        now = timezone.now()
        matchmake(now)
        for match in Match.objects.filter(mode=Match.Mode.RANKED, status=Match.Status.ACTIVE):
            reconcile(match, now)
        RankedConnection.objects.filter(
            last_seen__lt=now - timedelta(seconds=rule("presence_seconds"))
        ).delete()
