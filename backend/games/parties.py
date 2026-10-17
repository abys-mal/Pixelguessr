"""Durable party transitions; the party UPDATE is the cross-database writer lock."""

import secrets
import string
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from accounts.identity import honorary_title

from .models import (
    Guess,
    Match,
    Participant,
    Party,
    PartyCommand,
    PartyMember,
    Round,
    RoundPlayerState,
)
from .reveal import prepare_image
from .services import (
    GUEST_KEY,
    GameError,
    approved_images,
    choose_image,
    create_identity,
    image_fields,
    normalize_guess,
    revealed_count,
    score_for_reveal,
)

MAX_PLAYERS = 12
COUNTDOWN_SECONDS = 3
RESULT_SECONDS = 5
PRESENCE_SECONDS = 15
RECONNECT_GRACE_SECONDS = 15
END_MESSAGES = {
    "host_suspended": "The party ended because its host was suspended.",
    "host_closed": "The party ended because its host's account was closed.",
    "host_left": "The host left the party.",
    "host_disconnected": "The host disconnected.",
    "not_enough_players": "Not enough players remain.",
}


def group_name(code):
    return f"party.{code}"


def notify(party):
    # Only invalidations go through Channels. Each connection gets its own safe snapshot.
    transaction.on_commit(
        lambda: async_to_sync(get_channel_layer().group_send)(
            group_name(party.code), {"type": "party.changed"}
        ),
        robust=True,
    )


def changed(party):
    party.revision += 1
    party.save()
    notify(party)


def identity_filter(request):
    owner = Q(pk__in=[])
    if request.user.is_authenticated:
        owner |= Q(user=request.user)
    if request.session.get(GUEST_KEY):
        owner |= Q(guest_id=request.session[GUEST_KEY], guest__expires_at__gt=timezone.now())
    return owner


def check_access(request):
    from moderation.services import closed_session

    if closed_session(request):
        raise GameError("Your account has been closed.", "account_closed", 403)
    if request.user.is_authenticated:
        from moderation.services import account_restrictions

        restrictions = account_restrictions(request.user)
        if restrictions["blocked"] or restrictions["suspension"]:
            raise GameError(
                "Suspension prevents party participation."
                if restrictions["suspension"]
                else "Your account has been closed.",
                "party_restricted",
                403,
            )


def member_for(party, request, *, terminal=False):
    check_access(request)
    matches = party.members.filter(identity_filter(request))
    if matches.filter(banned_at__isnull=False).exists():
        raise GameError("You were removed and cannot rejoin this party.", "party_banned", 403)
    member = matches.filter(left_at__isnull=True).first()
    if not member:
        previous = matches.first()
        if (
            previous
            and previous.departure_reason == "host_ended"
            and terminal
            and party.end_reason in ("host_suspended", "host_closed")
        ):
            return previous
        if previous and previous.departure_reason in ("suspended", "closed"):
            raise GameError(
                "You were removed because suspension prevents party participation."
                if previous.departure_reason == "suspended"
                else "Your account has been closed.",
                "party_restricted",
                403,
            )
        if previous and previous.departure_reason in ("kicked", "disconnected"):
            code = (
                "party_removed" if previous.departure_reason == "kicked" else "membership_expired"
            )
            message = (
                "You were removed from this party."
                if code == "party_removed"
                else "Your connection to this party expired."
            )
            raise GameError(message, code, 403)
        raise NotFound("Join this party before continuing.")
    return member


def lock_party(code, *, allow_closed=False):
    # FIRST operation in a transaction: SQLite ignores FOR UPDATE.
    if not Party.objects.filter(code=code.upper()).update(revision=F("revision")):
        raise NotFound("That party code is invalid.")
    party = Party.objects.get(code=code.upper())
    if timezone.now() >= party.expires_at or (
        party.status == Party.Status.CLOSED and not allow_closed
    ):
        raise GameError(
            "This party has closed or expired. Create a new party.", "party_closed", 410
        )
    return party


def automatic_guest_name(party, existing):
    # Names are presentation only; identity stays in the existing signed server session.
    used = set(
        party.members.filter(left_at__isnull=True)
        .exclude(pk=existing.pk if existing else None)
        .values_list("name_key", flat=True)
    )
    if existing and existing.display_name.casefold() not in used:
        return existing.display_name
    first = secrets.randbelow(9000)
    for offset in range(9000):
        name = f"Guest {1000 + (first + offset) % 9000}"
        if name.casefold() not in used:
            return name
    raise GameError("Unable to assign a guest name.", "name_unavailable", 503)


def add_member(party, request, now):
    check_access(request)
    matches = party.members.filter(identity_filter(request))
    if matches.filter(banned_at__isnull=False).exists():
        raise GameError("You were removed and cannot rejoin this party.", "party_banned", 403)
    existing = matches.first()
    if existing and existing.left_at is None:
        existing.last_seen = now
        existing.save(update_fields=["last_seen"])
        return existing
    if party.status != Party.Status.LOBBY:
        raise GameError("This game has started or ended. Join a new party.", "match_started")
    if party.members.filter(left_at__isnull=True).count() >= MAX_PLAYERS:
        raise GameError("This party is full (12 players).", "party_full")
    name = (
        (request.user.display_name or request.user.username)[:40]
        if request.user.is_authenticated
        else automatic_guest_name(party, existing)
    )
    original = name
    index = 2
    while (
        party.members.filter(left_at__isnull=True, name_key=name.casefold())
        .exclude(pk=existing.pk if existing else None)
        .exists()
    ):
        name = f"{original[:32]} ({index})"
        index += 1
    if existing:
        existing.display_name = name
        existing.name_key = name.casefold()
        existing.last_seen = now
        existing.left_at = None
        existing.departure_reason = ""
        existing.joined_at = now
        existing.save()
        member = existing
    else:
        member = PartyMember.objects.create(
            party=party,
            display_name=name,
            name_key=name.casefold(),
            last_seen=now,
            **create_identity(request, now),
        )
    if not party.host_id:
        party.host = member
    changed(party)
    return member


def refresh_account_name(user):
    """Refresh live aliases under the party lock; preserve departed/historical names."""
    now = timezone.now()
    codes = Party.objects.filter(
        members__user=user,
        members__left_at__isnull=True,
        expires_at__gt=now,
    ).exclude(status__in=[Party.Status.CLOSED, Party.Status.ABORTED])
    for code in codes.order_by("code").values_list("code", flat=True):
        try:
            party = lock_party(code)
        except GameError as exc:
            if exc.detail.get("code") == "party_closed":
                continue
            raise
        member = party.members.filter(user=user, left_at__isnull=True).first()
        if not member:
            continue
        original = (user.display_name or user.username)[:40]
        name = original
        index = 2
        while (
            party.members.filter(left_at__isnull=True, name_key=name.casefold())
            .exclude(pk=member.pk)
            .exists()
        ):
            # Party aliases already disambiguate names; the account username is exact.
            name = f"{original[:32]} ({index})"
            index += 1
        if member.display_name != name:
            member.display_name = name
            member.name_key = name.casefold()
            member.save(update_fields=["display_name", "name_key"])
            changed(party)


def create_party(request, data):
    check_access(request)
    now = timezone.now()
    identity = create_identity(request, now)
    with transaction.atomic():
        owner = next(iter(identity.values()))
        owner._meta.model.objects.filter(pk=owner.pk).update(display_name=F("display_name"))
        check_access(request)
        existing = Party.objects.filter(create_request_id=data["request_id"]).first()
        if existing:
            member_for(existing, request)
            return existing.code
        while True:
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            try:
                with transaction.atomic():
                    party = Party.objects.create(
                        code=code,
                        create_request_id=data["request_id"],
                        reveal_seconds=data.get("reveal_seconds", 30),
                        round_limit=data.get("round_limit", 10),
                        expires_at=now + timedelta(days=1),
                    )
                break
            except IntegrityError:
                existing = Party.objects.filter(create_request_id=data["request_id"]).first()
                if existing:
                    member_for(existing, request)
                    return existing.code
                if not Party.objects.filter(code=code).exists():
                    raise
        add_member(party, request, now)
    return party.code


def join_party(request, code):
    check_access(request)
    # Commit due terminal transitions even if joining is subsequently rejected.
    with transaction.atomic():
        party = lock_party(code, allow_closed=True)
        advance(party, timezone.now())
    with transaction.atomic():
        party = lock_party(code)
        add_member(party, request, timezone.now())
    return party.code


def require_host(party, member):
    if party.host_id != member.pk:
        raise GameError("Only the host can do that.", "host_only", 403)


def end_party(party, reason, now):
    if party.status in (Party.Status.ABORTED, Party.Status.CLOSED):
        return
    if party.status == Party.Status.PLAYING:
        match = party.current_match
        match.status = Match.Status.ABORTED
        match.party_abort_reason = reason
        match.completed_at = now
        match.save(update_fields=["status", "party_abort_reason", "completed_at"])
        party.status = Party.Status.ABORTED
    else:
        party.status = Party.Status.CLOSED
    party.end_reason = reason
    party.message = ""
    changed(party)


def reconcile_members(party, now):
    from moderation.enforcement import enforce_party

    enforce_party(party, now)
    if party.status in (Party.Status.ABORTED, Party.Status.CLOSED):
        return
    members = list(party.members.filter(left_at__isnull=True))
    host = next((m for m in members if m.pk == party.host_id), None)
    if not host or (now - host.last_seen).total_seconds() > RECONNECT_GRACE_SECONDS:
        end_party(party, "host_disconnected", now)
        return
    expired = [
        m
        for m in members
        if m.pk != party.host_id and (now - m.last_seen).total_seconds() > RECONNECT_GRACE_SECONDS
    ]
    for member in expired:
        member.left_at = member.last_seen + timedelta(seconds=RECONNECT_GRACE_SECONDS)
        member.departure_reason = "disconnected"
        member.save(update_fields=["left_at", "departure_reason"])
    if expired:
        changed(party)
    if expired and party.status == Party.Status.PLAYING and len(members) - len(expired) < 2:
        end_party(party, "not_enough_players", now)


def settings_party(request, code, data):
    party_state(request, code, heartbeat=True)
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        require_host(party, member)
        if party.status != Party.Status.LOBBY:
            raise GameError(
                "Settings are locked until the party returns to the lobby.", "settings_locked"
            )
        for field in ("reveal_seconds", "round_limit"):
            if field in data:
                setattr(party, field, data[field])
        changed(party)


def command_seen(party, member, action, request_id, *, target=None, prevent_rejoin=False):
    previous = PartyCommand.objects.filter(pk=request_id).first()
    if previous:
        if (
            previous.party_id != party.pk
            or previous.member_id != member.pk
            or previous.action != action
            or previous.target_id != (target.pk if target else None)
            or previous.prevent_rejoin != prevent_rejoin
        ):
            raise GameError("This request was already used for another action.", "request_conflict")
        return True
    try:
        with transaction.atomic():
            PartyCommand.objects.create(
                request_id=request_id,
                party=party,
                member=member,
                action=action,
                target=target,
                prevent_rejoin=prevent_rejoin,
            )
    except IntegrityError:
        raise GameError("This request was already used.", "request_conflict") from None
    return False


def activate(party, game_round, start_at):
    used = list(
        game_round.match.rounds.filter(reveal_started_at__isnull=False)
        .order_by("number")
        .values_list("image_id", flat=True)
    )
    image = choose_image(
        approved_images(), used, used[-1] if used else None, preferred=game_round.image_id
    )
    prepare_image(image.image_file.name)
    for key, value in image_fields(image).items():
        setattr(game_round, key, value)
    game_round.reveal_started_at = start_at
    game_round.save()
    for participant in game_round.match.participants.all():
        RoundPlayerState.objects.create(
            round=game_round, participant=participant, total_before=participant.total_score
        )
    party.message = ""
    changed(party)


def start_party(request, code, request_id):
    party_state(request, code, heartbeat=True)
    with transaction.atomic():
        party = lock_party(code)
        now = timezone.now()
        member = member_for(party, request)
        require_host(party, member)
        if command_seen(party, member, "start", request_id):
            return
        if party.status != Party.Status.LOBBY:
            raise GameError("Return to the lobby before starting another game.", "match_started")
        members = list(
            party.members.filter(left_at__isnull=True)
            .select_related("user__verified_title")
            .order_by("joined_at", "id")
        )
        if len(members) < 2:
            raise GameError("At least two players are needed to start.", "not_enough_players")
        images = approved_images()
        match = Match.objects.create(
            mode=Match.Mode.PARTY, status=Match.Status.ACTIVE, party_round_limit=party.round_limit
        )
        for item in members:
            Participant.objects.create(
                match=match, party_member=item, user=item.user, guest=item.guest
            )
        used = []
        for number in range(1, party.round_limit + 1):
            image = choose_image(images, used, used[-1] if used else None)
            used.append(image.pk)
            order = list(range(settings.SINGLEPLAYER_GRID_SIZE**2))
            secrets.SystemRandom().shuffle(order)
            Round.objects.create(
                match=match,
                number=number,
                grid_size=settings.SINGLEPLAYER_GRID_SIZE,
                reveal_duration_seconds=party.reveal_seconds,
                reveal_order=order,
                **image_fields(image),
            )
        party.current_match = match
        party.status = Party.Status.PLAYING
        activate(party, match.rounds.get(number=1), now + timedelta(seconds=COUNTDOWN_SECONDS))


def finish(party, game_round, ended_at):
    if game_round.ended_at:
        return
    for state in game_round.player_states.select_related("participant"):
        total = max(0, state.total_before + state.score)
        state.participant.total_score = total
        state.participant.save(update_fields=["total_score"])
        state.total_after = total
        state.finalized_at = ended_at
        state.save(update_fields=["total_after", "finalized_at"])
    game_round.ended_at = ended_at
    game_round.outcome = Round.Outcome.COMPLETE
    game_round.save(update_fields=["ended_at", "outcome"])
    if game_round.number == game_round.match.party_round_limit:
        game_round.match.status = Match.Status.COMPLETE
        game_round.match.completed_at = ended_at
        game_round.match.save(update_fields=["status", "completed_at"])
    changed(party)


def current_round(party):
    return (
        Round.objects.filter(match_id=party.current_match_id, reveal_started_at__isnull=False)
        .select_related("match", "image__category")
        .order_by("-number")
        .first()
    )


def advance(party, now):
    reconcile_members(party, now)
    if party.status != Party.Status.PLAYING:
        return
    game_round = current_round(party)
    while game_round:
        deadline = game_round.reveal_started_at + timedelta(
            seconds=game_round.reveal_duration_seconds
        )
        if not game_round.ended_at and now >= deadline:
            finish(party, game_round, deadline)
        elif (
            not game_round.ended_at
            and now >= game_round.reveal_started_at
            and not game_round.player_states.filter(
                participant__party_member__left_at__isnull=True, solved_at__isnull=True
            ).exists()
        ):
            finish(party, game_round, now)
        if not game_round.ended_at or party.status == Party.Status.COMPLETE:
            return
        next_at = game_round.ended_at + timedelta(seconds=RESULT_SECONDS)
        if now < next_at:
            return
        if game_round.number == game_round.match.party_round_limit:
            party.status = Party.Status.COMPLETE
            changed(party)
            return
        target = game_round.match.rounds.select_related("match").get(number=game_round.number + 1)
        try:
            activate(
                party,
                target,
                (now if party.message else next_at) + timedelta(seconds=COUNTDOWN_SECONDS),
            )
        except GameError as exc:
            message = str(exc.detail["detail"])
            if party.message != message:
                party.message = message
                changed(party)
            return
        game_round = current_round(party)


def touch(request, code):
    party_state(request, code, heartbeat=True)


def remove_member(party, member, now, *, reason, ban=False):
    member.left_at = now
    member.departure_reason = reason
    if ban:
        member.banned_at = now
    member.save(update_fields=["left_at", "departure_reason", "banned_at"])
    if party.host_id == member.pk:
        end_party(party, "host_left", now)
    elif party.status == Party.Status.PLAYING:
        if party.members.filter(left_at__isnull=True).count() < 2:
            end_party(party, "not_enough_players", now)
        else:
            game_round = current_round(party)
            if (
                not game_round.ended_at
                and not game_round.player_states.filter(
                    participant__party_member__left_at__isnull=True, solved_at__isnull=True
                ).exists()
            ):
                finish(party, game_round, now)
    if not party.members.filter(left_at__isnull=True).exists():
        party.status = Party.Status.CLOSED
    changed(party)


def leave_party(request, code):
    with transaction.atomic():
        party = lock_party(code, allow_closed=True)
        member = member_for(party, request)
        remove_member(party, member, timezone.now(), reason="left")


def kick_party(request, code, target_id, prevent_rejoin, request_id):
    party_state(request, code, heartbeat=True)
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        require_host(party, member)
        target = party.members.filter(pk=target_id).first()
        if not target:
            raise NotFound("That player is not in this party.")
        if target.pk == party.host_id:
            raise GameError("The host cannot remove themselves.", "cannot_kick_host", 400)
        if command_seen(
            party, member, "kick", request_id, target=target, prevent_rejoin=prevent_rejoin
        ):
            return
        if party.status not in (Party.Status.LOBBY, Party.Status.PLAYING):
            raise GameError("This party has ended.", "party_ended")
        if target.left_at:
            raise NotFound("That player is no longer in this party.")
        remove_member(party, target, timezone.now(), reason="kicked", ban=prevent_rejoin)


def lobby_party(request, code, request_id):
    party_state(request, code, heartbeat=True)
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        advance(party, timezone.now())
        if command_seen(party, member, "lobby", request_id):
            return
        if party.status != Party.Status.COMPLETE:
            raise GameError(
                "The match must finish before returning to the lobby.", "match_unfinished"
            )
        party.status = Party.Status.LOBBY
        party.message = ""
        changed(party)


def submit_party_guess(request, code, round_id, text, request_id):
    error = None
    result = None
    with transaction.atomic():
        party = lock_party(code)
        member_for(party, request)
        now = timezone.now()
        advance(party, now)
        try:
            # Recheck membership after grace reconciliation in the SAME writer transaction.
            member = member_for(party, request)
            result = record_party_guess(party, member, round_id, text, request_id, now)
        except APIException as exc:
            error = exc
    # Due departures/deadlines must commit even when this guess is rejected.
    if error:
        raise error
    return result


def record_party_guess(party, member, round_id, text, request_id, now):
    if party.status == Party.Status.ABORTED:
        raise GameError(END_MESSAGES.get(party.end_reason, "This match ended."), "match_aborted")
    previous = Guess.objects.filter(request_id=request_id).first()
    if previous:
        if (
            previous.round_id != round_id
            or previous.participant.party_member_id != member.pk
            or normalize_guess(previous.text) != normalize_guess(text)
        ):
            raise GameError("This request was used for another guess.", "request_conflict")
        return "correct" if previous.correct else "incorrect"
    game_round = current_round(party)
    if (
        party.status != Party.Status.PLAYING
        or not game_round
        or game_round.pk != round_id
        or game_round.ended_at
    ):
        raise GameError("This round has ended or is no longer current.", "round_ended")
    if now < game_round.reveal_started_at:
        raise GameError("Wait for the round to begin.", "round_not_started")
    state = game_round.player_states.select_related("participant").get(
        participant__party_member=member
    )
    if state.solved_at:
        raise GameError("You already solved this round. Watch until it ends.", "already_solved")
    if state.cooldown_until and now < state.cooldown_until:
        raise GameError("Wait two seconds after an incorrect guess.", "guess_cooldown", 429)
    accepted = [game_round.answer_snapshot, *game_round.synonyms_snapshot]
    correct = normalize_guess(text) in {normalize_guess(answer) for answer in accepted}
    Guess.objects.create(
        round=game_round,
        participant=state.participant,
        sequence=game_round.guesses.filter(participant=state.participant).count() + 1,
        request_id=request_id,
        text=text,
        correct=correct,
    )
    if correct:
        count = revealed_count(game_round, now)
        state.score = score_for_reveal(count, game_round.grid_size**2) - 50 * state.incorrect_count
        state.solved_at = now
        state.solve_revealed_count = count
        state.cooldown_until = None
    else:
        state.incorrect_count += 1
        state.score = -50 * state.incorrect_count
        state.cooldown_until = now + timedelta(seconds=2)
    state.save()
    state.participant.total_score = max(0, state.total_before + state.score)
    state.participant.save(update_fields=["total_score"])
    if not game_round.player_states.filter(
        participant__party_member__left_at__isnull=True, solved_at__isnull=True
    ).exists():
        finish(party, game_round, now)
    changed(party)
    return "correct" if correct else "incorrect"


def payload(party, member, now):
    members = list(
        party.members.filter(left_at__isnull=True)
        .select_related("user__verified_title")
        .order_by("joined_at", "id")
    )
    game_round = (
        current_round(party)
        if party.status in (Party.Status.PLAYING, Party.Status.COMPLETE)
        else None
    )
    data = {
        "code": party.code,
        "status": party.status,
        "revision": party.revision,
        "server_now": now.isoformat(),
        "expires_at": party.expires_at.isoformat(),
        "host_id": str(party.host_id) if party.host_id else None,
        "me_id": str(member.pk),
        "settings": {"reveal_seconds": party.reveal_seconds, "round_limit": party.round_limit},
        "members": [
            {
                "id": str(m.pk),
                "name": m.display_name,
                "title": honorary_title(m.user),
                "connected": (now - m.last_seen).total_seconds() <= PRESENCE_SECONDS,
            }
            for m in members
        ],
        "match_id": str(party.current_match_id) if party.current_match_id else None,
        "round": None,
        "leaderboard": [],
        "winners": [],
        "message": party.message,
        "notice": party_notice(party),
        "end_reason": party.end_reason,
        "end_message": END_MESSAGES.get(party.end_reason, ""),
        "rules": {
            "max_players": MAX_PLAYERS,
            "countdown_seconds": COUNTDOWN_SECONDS,
            "results_seconds": RESULT_SECONDS,
            "wrong_penalty": 50,
            "cooldown_seconds": 2,
        },
    }
    if not game_round:
        return data
    count = game_round.grid_size**2 if game_round.ended_at else revealed_count(game_round, now)
    deadline = game_round.reveal_started_at + timedelta(seconds=game_round.reveal_duration_seconds)
    states = list(
        game_round.player_states.select_related("participant__party_member__user__verified_title")
    )
    me = next(s for s in states if s.participant.party_member_id == member.pk)
    rank = sorted(
        states,
        key=lambda s: (
            -s.score,
            s.solved_at or deadline,
            s.participant.joined_at,
            str(s.participant.pk),
        ),
    )
    round_ranks = {s.participant_id: i for i, s in enumerate(rank, 1)}
    # Ties in total points share the win; secondary keys only make display order stable.
    totals = []
    for state in states:
        history = list(
            RoundPlayerState.objects.filter(
                participant=state.participant, solved_at__isnull=False
            ).select_related("round")
        )
        solve_time = sum((s.solved_at - s.round.reveal_started_at).total_seconds() for s in history)
        item = state.participant.party_member
        totals.append((state, len(history), solve_time, item))
    totals.sort(
        key=lambda entry: (
            -entry[0].participant.total_score,
            -entry[1],
            entry[2],
            entry[3].joined_at,
            str(entry[3].pk),
        )
    )
    data["leaderboard"] = [
        {
            "id": str(item.pk),
            "name": item.display_name,
            "title": honorary_title(item.user),
            "total_score": state.participant.total_score,
            "round_score": state.score,
            "solved": bool(state.solved_at),
            "connected": not item.left_at
            and (now - item.last_seen).total_seconds() <= PRESENCE_SECONDS,
            "left": bool(item.left_at),
            "round_rank": round_ranks[state.participant_id],
            "solved_rounds": solved,
        }
        for state, solved, _, item in totals
    ]
    if party.status == Party.Status.COMPLETE:
        best = totals[0][0].participant.total_score
        data["winners"] = [
            str(item.pk) for state, _, _, item in totals if state.participant.total_score == best
        ]
    data["round"] = {
        "id": str(game_round.pk),
        "number": game_round.number,
        "status": "results"
        if game_round.ended_at
        else "countdown"
        if now < game_round.reveal_started_at
        else "active",
        "started_at": game_round.reveal_started_at.isoformat(),
        "reveal_finishes_at": deadline.isoformat(),
        "next_starts_at": (game_round.ended_at + timedelta(seconds=RESULT_SECONDS)).isoformat()
        if game_round.ended_at and party.status != Party.Status.COMPLETE
        else None,
        "grid_size": game_round.grid_size,
        "revealed_count": count,
        "total_tiles": game_round.grid_size**2,
        "revealed_tiles": game_round.reveal_order[:count],
        "image_url": f"/api/parties/{party.code}/rounds/{game_round.pk}/image/?v={count}",
        "completion": {
            "answer": game_round.answer_snapshot,
            "license": game_round.image.license,
            "attribution": game_round.image.attribution,
            "category": game_round.image.category.name,
        }
        if game_round.ended_at
        else None,
        "me": {
            "solved": bool(me.solved_at),
            "round_score": me.score,
            "guess_count": game_round.guesses.filter(participant=me.participant).count(),
            "incorrect_count": me.incorrect_count,
            "cooldown_until": me.cooldown_until.isoformat() if me.cooldown_until else None,
        },
    }
    return data


def party_state(request, code, *, heartbeat=False):
    error = None
    with transaction.atomic():
        party = lock_party(code, allow_closed=True)
        member = member_for(party, request, terminal=True)
        now = timezone.now()
        # Check elapsed grace BEFORE renewing presence, so late reconnects cannot resurrect a match.
        advance(party, now)
        member.refresh_from_db()
        if member.left_at and member.departure_reason != "host_ended":
            error = GameError("Your connection to this party expired.", "membership_expired", 403)
            data = None
        else:
            if heartbeat and party.status not in (Party.Status.ABORTED, Party.Status.CLOSED):
                member.last_seen = now
                member.save(update_fields=["last_seen"])
            data = payload(party, member, now)
    if error:
        raise error
    return data


def party_notice(party):
    removed = (
        party.members.filter(departure_reason__in=["suspended", "closed"])
        .order_by("-left_at")
        .first()
    )
    return (
        f"{removed.display_name} was removed from the party due to an account restriction."
        if removed
        else ""
    )


def party_image(request, code, round_id):
    party_state(request, code)
    with transaction.atomic():
        party = lock_party(code)
        member_for(party, request)
        now = timezone.now()
        advance(party, now)
        game_round = current_round(party)
        if (
            party.status not in (Party.Status.PLAYING, Party.Status.COMPLETE)
            or not game_round
            or game_round.pk != round_id
        ):
            raise NotFound("Only the current round image is available.")
        count = game_round.grid_size**2 if game_round.ended_at else revealed_count(game_round, now)
        return game_round, now, count


def clock_tick():
    """Idempotent clock; multiple processes serialize on each party's database row."""
    for code in Party.objects.exclude(status=Party.Status.CLOSED).values_list("code", flat=True):
        with transaction.atomic():
            Party.objects.filter(code=code).update(revision=F("revision"))
            party = Party.objects.get(code=code)
            now = timezone.now()
            if now >= party.expires_at:
                party.status = Party.Status.CLOSED
                if party.current_match_id:
                    Match.objects.filter(
                        pk=party.current_match_id, status=Match.Status.ACTIVE
                    ).update(status=Match.Status.ABANDONED)
                changed(party)
            else:
                advance(party, now)
