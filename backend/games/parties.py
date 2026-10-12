"""Durable party transitions; the party UPDATE is the cross-database writer lock."""

import secrets
import string
import unicodedata
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

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
HOST_GRACE_SECONDS = 45


def group_name(code):
    return f"party.{code}"


def notify(party):
    # Only invalidations go through Channels. Each connection gets its own safe snapshot.
    transaction.on_commit(
        lambda: async_to_sync(get_channel_layer().group_send)(
            group_name(party.code), {"type": "party.changed"}
        )
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
    if request.user.is_authenticated:
        from moderation.services import account_restrictions

        restrictions = account_restrictions(request.user)
        if restrictions["blocked"] or restrictions["unacknowledged_warnings"]:
            raise PermissionDenied("This account must resolve its restriction before playing.")


def member_for(party, request):
    check_access(request)
    member = party.members.filter(identity_filter(request), left_at__isnull=True).first()
    if not member:
        raise NotFound("Join this party before continuing.")
    return member


def lock_party(code):
    # Make this the FIRST database operation in a transaction. SQLite ignores FOR UPDATE.
    if not Party.objects.filter(code=code.upper()).update(revision=F("revision")):
        raise NotFound("That party code is invalid.")
    party = Party.objects.get(code=code.upper())
    if party.status == Party.Status.CLOSED or timezone.now() >= party.expires_at:
        raise GameError(
            "This party has closed or expired. Create a new party.", "party_closed", 410
        )
    return party


def guest_name(value):
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 2 <= len(value) <= 24 or any(
        unicodedata.category(c)[0] not in "LN" and c not in " .-_’'" for c in value
    ):
        raise GameError(
            "Use a display name of 2–24 letters, numbers, spaces, or simple punctuation.",
            "invalid_name",
            400,
        )
    if not any(unicodedata.category(c)[0] in "LN" for c in value):
        raise GameError("Your display name needs a letter or number.", "invalid_name", 400)
    return value


def add_member(party, request, name, now):
    existing = party.members.filter(identity_filter(request)).first()
    if existing and existing.left_at is None:
        existing.last_seen = now
        existing.save(update_fields=["last_seen"])
        return existing
    if party.status != Party.Status.LOBBY:
        raise GameError(
            "This game has started. Join when the party returns to the lobby.", "match_started"
        )
    if party.members.filter(left_at__isnull=True).count() >= MAX_PLAYERS:
        raise GameError("This party is full (12 players).", "party_full")
    name = (
        (request.user.display_name or request.user.username)[:40]
        if request.user.is_authenticated
        else guest_name(name)
    )
    original = name
    index = 2
    while (
        party.members.filter(left_at__isnull=True, name_key=name.casefold())
        .exclude(pk=existing.pk if existing else None)
        .exists()
    ):
        if not request.user.is_authenticated:
            raise GameError(
                "That display name is already in this party. Choose another.", "name_taken", 400
            )
        name = f"{original[:32]} ({index})"
        index += 1
    if existing:
        existing.display_name = name
        existing.name_key = name.casefold()
        existing.last_seen = now
        existing.left_at = None
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


def create_party(request, data):
    check_access(request)
    now = timezone.now()
    identity = create_identity(request, now)
    with transaction.atomic():
        owner = next(iter(identity.values()))
        type(owner).objects.filter(pk=owner.pk).update(display_name=F("display_name"))
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
        add_member(party, request, data.get("display_name", ""), now)
    return party.code


def join_party(request, code, name):
    check_access(request)
    with transaction.atomic():
        party = lock_party(code)
        advance(party, timezone.now())
        add_member(party, request, name, timezone.now())
    return party.code


def require_host(party, member):
    if party.host_id != member.pk:
        raise GameError("Only the host can do that.", "host_only", 403)


def succession(party, now):
    members = list(party.members.filter(left_at__isnull=True).order_by("joined_at", "id"))
    host = next((m for m in members if m.pk == party.host_id), None)
    if not host or (now - host.last_seen).total_seconds() > HOST_GRACE_SECONDS:
        successor = next(
            (m for m in members if (now - m.last_seen).total_seconds() <= HOST_GRACE_SECONDS), None
        )
        if party.host_id != (successor.pk if successor else None):
            party.host = successor
            changed(party)


def settings_party(request, code, data):
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        succession(party, timezone.now())
        require_host(party, member)
        if party.status != Party.Status.LOBBY:
            raise GameError(
                "Settings are locked until the party returns to the lobby.", "settings_locked"
            )
        for field in ("reveal_seconds", "round_limit"):
            if field in data:
                setattr(party, field, data[field])
        changed(party)


def command_seen(party, member, action, request_id):
    previous = PartyCommand.objects.filter(pk=request_id).first()
    if previous:
        if (
            previous.party_id != party.pk
            or previous.member_id != member.pk
            or previous.action != action
        ):
            raise GameError("This request was already used for another action.", "request_conflict")
        return True
    try:
        with transaction.atomic():
            PartyCommand.objects.create(
                request_id=request_id, party=party, member=member, action=action
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
    with transaction.atomic():
        party = lock_party(code)
        now = timezone.now()
        member = member_for(party, request)
        succession(party, now)
        require_host(party, member)
        if command_seen(party, member, "start", request_id):
            return
        if party.status != Party.Status.LOBBY:
            raise GameError("Return to the lobby before starting another game.", "match_started")
        members = list(party.members.filter(left_at__isnull=True).order_by("joined_at", "id"))
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
    succession(party, now)
    if party.status != Party.Status.PLAYING:
        return
    game_round = current_round(party)
    while game_round:
        deadline = game_round.reveal_started_at + timedelta(
            seconds=game_round.reveal_duration_seconds
        )
        if not game_round.ended_at and now >= deadline:
            finish(party, game_round, deadline)
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
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        member.last_seen = timezone.now()
        member.save(update_fields=["last_seen"])
        succession(party, member.last_seen)


def leave_party(request, code):
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        now = timezone.now()
        member.left_at = now
        member.save(update_fields=["left_at"])
        if party.host_id == member.pk:
            party.host = (
                party.members.filter(left_at__isnull=True).order_by("joined_at", "id").first()
            )
        if not party.members.filter(left_at__isnull=True).exists():
            party.status = Party.Status.CLOSED
            if party.current_match_id:
                Match.objects.filter(pk=party.current_match_id, status=Match.Status.ACTIVE).update(
                    status=Match.Status.ABANDONED
                )
        elif party.status == Party.Status.PLAYING:
            game_round = current_round(party)
            if (
                not game_round.ended_at
                and not game_round.player_states.filter(
                    participant__party_member__left_at__isnull=True, solved_at__isnull=True
                ).exists()
            ):
                finish(party, game_round, now)
        changed(party)


def lobby_party(request, code, request_id):
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
    # Commit due transitions independently of any subsequent invalid guess rejection.
    with transaction.atomic():
        party = lock_party(code)
        member_for(party, request)
        advance(party, timezone.now())
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        now = timezone.now()
        advance(party, now)
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
            state.score = (
                score_for_reveal(count, game_round.grid_size**2) - 50 * state.incorrect_count
            )
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
    members = list(party.members.filter(left_at__isnull=True).order_by("joined_at", "id"))
    game_round = current_round(party) if party.status != Party.Status.LOBBY else None
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
                "connected": (now - m.last_seen).total_seconds() <= PRESENCE_SECONDS,
            }
            for m in members
        ],
        "match_id": str(party.current_match_id) if party.current_match_id else None,
        "round": None,
        "leaderboard": [],
        "winners": [],
        "message": party.message,
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
    states = list(game_round.player_states.select_related("participant__party_member"))
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
    with transaction.atomic():
        party = lock_party(code)
        member = member_for(party, request)
        now = timezone.now()
        if heartbeat:
            member.last_seen = now
            member.save(update_fields=["last_seen"])
        advance(party, now)
        return payload(party, member, now)


def party_image(request, code, round_id):
    with transaction.atomic():
        party = lock_party(code)
        member_for(party, request)
        now = timezone.now()
        advance(party, now)
        game_round = current_round(party)
        if not game_round or game_round.pk != round_id or party.status == Party.Status.LOBBY:
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
