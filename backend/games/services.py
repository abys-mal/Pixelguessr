"""Singleplayer state transitions. Ownership and answer checking stay on the server."""

import math
import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

from library.models import ImageSubmission

from .models import Guess, GuestIdentity, Match, Participant, Round, RoundPlayerState

GUEST_KEY = "singleplayer_guest_id"
CURRENT_KEY = "singleplayer_round_id"


class GameError(APIException):
    def __init__(self, detail, code, status=409):
        self.status_code = status
        super().__init__({"detail": detail, "code": code})


def normalize_guess(value):
    # Normalize compatibility characters and case; punctuation is treated as a separator,
    # except apostrophes, which are removed (e.g. bird's -> birds).
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(
        "" if c in "'’" else " " if unicodedata.category(c)[0] in "PS" else c for c in value
    )
    return " ".join(value.split())


def owner_filter(request):
    owner = Q(pk__in=[])
    if request.user.is_authenticated:
        owner |= Q(match__participants__user=request.user)
    guest_id = request.session.get(GUEST_KEY)
    if guest_id:
        owner |= Q(
            match__participants__guest_id=guest_id,
            match__participants__guest__expires_at__gt=timezone.now(),
        )
    return owner


def owned_rounds(request):
    return Round.objects.filter(
        owner_filter(request), match__mode=Match.Mode.SINGLEPLAYER
    ).select_related("match", "image__category")


def owned_round(request, round_id):
    game_round = owned_rounds(request).filter(pk=round_id).first()
    if not game_round:
        raise NotFound("This round is unavailable in your current session.")
    return game_round


def participant_for(request, game_round):
    if request.user.is_authenticated:
        participant = game_round.match.participants.filter(user=request.user).first()
        if participant:
            return participant
    return game_round.match.participants.get(guest_id=request.session.get(GUEST_KEY))


def create_identity(request, now):
    if request.user.is_authenticated:
        return {"user": request.user}
    guest = GuestIdentity.objects.filter(
        pk=request.session.get(GUEST_KEY), expires_at__gt=now
    ).first()
    if not guest:
        guest = GuestIdentity.objects.create(
            display_name="Guest", expires_at=now + timedelta(days=7)
        )
    else:
        guest.expires_at = now + timedelta(days=7)
        guest.save(update_fields=["expires_at"])
    request.session[GUEST_KEY] = str(guest.id)
    request.session.set_expiry(7 * 86400)
    return {"guest": guest}


def start_round(request, request_id):
    existing = Round.objects.filter(start_request_id=request_id).first()
    if existing:
        game_round = owned_round(request, existing.pk)
        request.session[CURRENT_KEY] = str(game_round.pk)
        return game_round
    image = (
        ImageSubmission.objects.filter(status=ImageSubmission.Status.APPROVED)
        .exclude(image_file="")
        .order_by("?")
        .first()
    )
    if not image:
        raise GameError(
            "There are no approved hosted images to play yet. Add images and review them in Admin.",
            "library_empty",
            503,
        )
    # Validate readable private storage before allocating a round. Never fetch external URLs.
    from .reveal import prepare_image

    prepare_image(image.image_file.name)
    now = timezone.now()
    identity = create_identity(request, now)
    grid_size = settings.SINGLEPLAYER_GRID_SIZE
    order = list(range(grid_size * grid_size))
    secrets.SystemRandom().shuffle(order)
    previous_id = request.session.get(CURRENT_KEY)
    try:
        with transaction.atomic():
            # First transactional operation is a write: this also serializes SQLite writers.
            match = Match.objects.create(mode=Match.Mode.SINGLEPLAYER, status=Match.Status.ACTIVE)
            image = ImageSubmission.objects.filter(
                pk=image.pk,
                status=ImageSubmission.Status.APPROVED,
                image_file=image.image_file.name,
            ).first()
            if not image:
                raise GameError(
                    "This picture's review changed. Please start again.", "image_unavailable", 503
                )
            participant = Participant.objects.create(match=match, **identity)
            game_round = Round.objects.create(
                match=match,
                image=image,
                number=1,
                start_request_id=request_id,
                grid_size=grid_size,
                reveal_duration_seconds=settings.SINGLEPLAYER_REVEAL_SECONDS,
                reveal_order=order,
                reveal_started_at=now,
                expires_at=now + timedelta(seconds=settings.SINGLEPLAYER_ROUND_TTL_SECONDS),
                answer_snapshot=image.canonical_answer,
                synonyms_snapshot=list(image.accepted_synonyms),
                image_storage_name=image.image_file.name,
            )
            RoundPlayerState.objects.create(round=game_round, participant=participant)
            if previous_id:
                previous = owned_rounds(request).filter(pk=previous_id).first()
                if previous and previous.match.status == Match.Status.ACTIVE:
                    Match.objects.filter(pk=previous.match_id, status=Match.Status.ACTIVE).update(
                        status=Match.Status.ABANDONED
                    )
                    Round.objects.filter(pk=previous.pk, ended_at__isnull=True).update(ended_at=now)
    except IntegrityError:
        existing = Round.objects.filter(start_request_id=request_id).first()
        if not existing:
            raise
        game_round = owned_round(request, existing.pk)
    request.session[CURRENT_KEY] = str(game_round.pk)
    return game_round


def expire_round(game_round, now):
    if (
        game_round.match.status == Match.Status.ACTIVE
        and game_round.expires_at
        and now >= game_round.expires_at
    ):
        changed = Match.objects.filter(pk=game_round.match_id, status=Match.Status.ACTIVE).update(
            status=Match.Status.ABANDONED
        )
        if changed:
            Round.objects.filter(pk=game_round.pk, ended_at__isnull=True).update(ended_at=now)
        # Re-read, because a correct guess could have won the race against expiry.
        game_round.match.refresh_from_db()
        game_round.refresh_from_db()


def revealed_count(game_round, now):
    total = game_round.grid_size**2
    if game_round.match.status == Match.Status.COMPLETE:
        return total
    elapsed = max(0, (now - game_round.reveal_started_at).total_seconds())
    return min(total, math.floor(total * elapsed / game_round.reveal_duration_seconds))


def snapshot(game_round, now=None):
    now = now or timezone.now()
    expire_round(game_round, now)
    state = (
        "solved"
        if game_round.match.status == Match.Status.COMPLETE
        else "active"
        if game_round.match.status == Match.Status.ACTIVE
        else "expired"
    )
    count = revealed_count(game_round, now)
    guesses = game_round.guesses.count()
    result = {
        "id": str(game_round.pk),
        "status": state,
        "server_now": now.isoformat(),
        "started_at": game_round.reveal_started_at.isoformat(),
        "reveal_finishes_at": (
            game_round.reveal_started_at + timedelta(seconds=game_round.reveal_duration_seconds)
        ).isoformat(),
        "expires_at": game_round.expires_at.isoformat(),
        "grid_size": game_round.grid_size,
        "revealed_count": count,
        "total_tiles": game_round.grid_size**2,
        "revealed_tiles": game_round.reveal_order[:count],
        "guess_count": guesses,
        "image_url": f"/api/games/singleplayer/rounds/{game_round.pk}/image/?v={count}"
        if state != "expired"
        else None,
        "completion": None,
    }
    if state == "solved":
        result["completion"] = {
            "answer": game_round.answer_snapshot,
            "solved_in_seconds": round(
                (game_round.ended_at - game_round.reveal_started_at).total_seconds(), 2
            ),
            "guesses": guesses,
            "license": game_round.image.license,
            "attribution": game_round.image.attribution,
            "category": game_round.image.category.name,
        }
    return result


def current_round(request):
    round_id = request.session.get(CURRENT_KEY)
    if not round_id:
        return None
    game_round = owned_rounds(request).filter(pk=round_id).first()
    return snapshot(game_round) if game_round else None


def submit_guess(request, round_id, text, request_id):
    game_round = owned_round(request, round_id)
    with transaction.atomic():
        # An UPDATE acquires the writer lock before reads on SQLite, and a row lock on
        # PostgreSQL. select_for_update alone would NOT serialize SQLite writers.
        Match.objects.filter(pk=game_round.match_id).update(status=F("status"))
        game_round = owned_round(request, round_id)
        now = timezone.now()
        expire_round(game_round, now)
        if game_round.match.status == Match.Status.COMPLETE:
            return {"round": snapshot(game_round, now), "result": "already_solved"}
        if game_round.match.status != Match.Status.ACTIVE:
            return {
                "round": snapshot(game_round, now),
                "result": "expired",
                "detail": "This round has expired. Start a new picture.",
                "code": "round_expired",
            }
        previous = Guess.objects.filter(request_id=request_id).first()
        if previous:
            if previous.round_id != game_round.pk or normalize_guess(
                previous.text
            ) != normalize_guess(text):
                raise GameError(
                    "This request was already used for a different guess.", "request_conflict"
                )
            return {
                "round": snapshot(game_round, now),
                "result": "correct" if previous.correct else "incorrect",
            }
        participant = participant_for(request, game_round)
        accepted = [game_round.answer_snapshot, *game_round.synonyms_snapshot]
        correct = normalize_guess(text) in {normalize_guess(answer) for answer in accepted}
        Guess.objects.create(
            round=game_round,
            participant=participant,
            sequence=game_round.guesses.count() + 1,
            request_id=request_id,
            text=text,
            correct=correct,
        )
        if correct:
            game_round.ended_at = now
            game_round.winner = participant
            game_round.save(update_fields=["ended_at", "winner"])
            game_round.match.status = Match.Status.COMPLETE
            game_round.match.completed_at = now
            game_round.match.save(update_fields=["status", "completed_at"])
            RoundPlayerState.objects.filter(round=game_round, participant=participant).update(
                solved_at=now
            )
        return {"round": snapshot(game_round, now), "result": "correct" if correct else "incorrect"}
