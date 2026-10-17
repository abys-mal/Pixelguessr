"""Singleplayer state transitions. Ownership and answer checking stay on the server."""

import math
import secrets
import unicodedata
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
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


ROUND_LIMIT = 5
COMPLETED = {Round.Outcome.SOLVED, Round.Outcome.FORFEITED}


def score_for_reveal(count, total):
    """Exact integer arithmetic, round half up (562.5 -> 563), no float ambiguity."""
    if total <= 0:
        raise ValueError("Tile count must be positive.")
    count = min(total, max(0, count))
    denominator = total * total
    return (2000 * (total - count) ** 2 + denominator) // (2 * denominator)


def approved_images():
    images = list(
        ImageSubmission.objects.filter(status="approved", retired_at__isnull=True).exclude(
            image_file=""
        )
    )
    if not images:
        raise GameError("No approved hosted images are available.", "library_empty", 503)
    return images


def choose_image(images, used, previous=None, preferred=None):
    counts = Counter(used)
    # Avoid an immediate repeat whenever another approved image exists.
    candidates = [image for image in images if image.pk != previous] if len(images) > 1 else images
    least_used = min(counts[image.pk] for image in candidates)
    candidates = [image for image in candidates if counts[image.pk] == least_used]
    return next((image for image in candidates if image.pk == preferred), None) or secrets.choice(
        candidates
    )


def image_fields(image):
    return {
        "image": image,
        "answer_snapshot": image.canonical_answer,
        "synonyms_snapshot": list(image.accepted_synonyms),
        "image_storage_name": image.image_file.name,
    }


def latest_started_round(match):
    return match.rounds.filter(reveal_started_at__isnull=False).order_by("-number").first()


def start_round(request, request_id):
    previous = Round.objects.filter(start_request_id=request_id).first()
    if previous:
        previous = owned_round(request, previous.pk)
        if previous.number != 1 or previous.match.singleplayer_round_limit != ROUND_LIMIT:
            raise GameError("Use a new request to start a five-round game.", "request_conflict")
        current = latest_started_round(previous.match)
        request.session[CURRENT_KEY] = str(current.pk)
        return current
    images = approved_images()
    plan, used = [], []
    for _ in range(ROUND_LIMIT):
        image = choose_image(images, used, used[-1] if used else None)
        plan.append(image)
        used.append(image.pk)
    from .reveal import prepare_image

    prepare_image(plan[0].image_file.name)
    now = timezone.now()
    identity = create_identity(request, now)
    previous_id = request.session.get(CURRENT_KEY)
    expiry = now + timedelta(seconds=settings.SINGLEPLAYER_ROUND_TTL_SECONDS)
    try:
        with transaction.atomic():
            # Shared owner lock serializes new starts even with different request UUIDs.
            # UPDATE also works on SQLite, where select_for_update has no effect.
            owner = next(iter(identity.values()))
            owner._meta.model.objects.filter(pk=owner.pk).update(display_name=F("display_name"))
            # Recheck idempotency after waiting for the owner lock.
            previous = Round.objects.filter(start_request_id=request_id).first()
            if previous:
                previous = owned_round(request, previous.pk)
                if previous.number != 1 or previous.match.singleplayer_round_limit != ROUND_LIMIT:
                    raise GameError("This request was already used.", "request_conflict")
                current = latest_started_round(previous.match)
                request.session[CURRENT_KEY] = str(current.pk)
                return current
            active = (
                owned_rounds(request)
                .filter(
                    match__status=Match.Status.ACTIVE,
                    match__singleplayer_round_limit=ROUND_LIMIT,
                    number=1,
                )
                .first()
            )
            if active:
                expire_round(active, now)
                if active.match.status == Match.Status.ACTIVE:
                    raise GameError(
                        "Finish the current game before starting another.", "session_in_progress"
                    )
            current_images = {
                image.pk: image
                for image in ImageSubmission.objects.filter(status="approved").exclude(
                    image_file=""
                )
            }
            for image in plan:
                reviewed = current_images.get(image.pk)
                if not reviewed or reviewed.image_file.name != image.image_file.name:
                    raise GameError(
                        "An image's review changed. Please retry.", "image_unavailable", 503
                    )
            match = Match.objects.create(
                mode=Match.Mode.SINGLEPLAYER,
                status=Match.Status.ACTIVE,
                singleplayer_round_limit=ROUND_LIMIT,
                singleplayer_expires_at=expiry,
                singleplayer_revision=1,
            )
            participant = Participant.objects.create(match=match, **identity)
            first = None
            for number, planned in enumerate(plan, 1):
                order = list(range(settings.SINGLEPLAYER_GRID_SIZE**2))
                secrets.SystemRandom().shuffle(order)
                game_round = Round.objects.create(
                    match=match,
                    number=number,
                    start_request_id=request_id if number == 1 else None,
                    grid_size=settings.SINGLEPLAYER_GRID_SIZE,
                    reveal_duration_seconds=settings.SINGLEPLAYER_REVEAL_SECONDS,
                    reveal_order=order,
                    reveal_started_at=now if number == 1 else None,
                    expires_at=expiry,
                    **image_fields(current_images[planned.pk]),
                )
                RoundPlayerState.objects.create(round=game_round, participant=participant)
                if number == 1:
                    first = game_round
            if previous_id:
                legacy = (
                    owned_rounds(request)
                    .filter(pk=previous_id, match__singleplayer_round_limit=1)
                    .first()
                )
                if legacy and legacy.match.status == Match.Status.ACTIVE:
                    Match.objects.filter(pk=legacy.match_id).update(status=Match.Status.ABANDONED)
                    Round.objects.filter(pk=legacy.pk, ended_at__isnull=True).update(
                        ended_at=now, outcome=Round.Outcome.EXPIRED
                    )
    except IntegrityError:
        previous = Round.objects.filter(start_request_id=request_id).first()
        if not previous:
            raise
        previous = owned_round(request, previous.pk)
        if previous.number != 1 or previous.match.singleplayer_round_limit != ROUND_LIMIT:
            raise GameError("This request was already used.", "request_conflict") from None
        first = latest_started_round(previous.match)
    request.session[CURRENT_KEY] = str(first.pk)
    return first


def expire_round(game_round, now):
    expiry = game_round.match.singleplayer_expires_at or game_round.expires_at
    if game_round.match.status == Match.Status.ACTIVE and expiry and now >= expiry:
        changed = Match.objects.filter(pk=game_round.match_id, status=Match.Status.ACTIVE).update(
            status=Match.Status.ABANDONED, singleplayer_revision=F("singleplayer_revision") + 1
        )
        if changed:
            Round.objects.filter(match_id=game_round.match_id, outcome="").update(
                outcome=Round.Outcome.EXPIRED, ended_at=now
            )
        game_round.match.refresh_from_db()
        game_round.refresh_from_db()


def revealed_count(game_round, now):
    total = game_round.grid_size**2
    if game_round.outcome in COMPLETED:
        return total
    if not game_round.reveal_started_at:
        return 0
    elapsed = max(0, (now - game_round.reveal_started_at).total_seconds())
    return min(total, math.floor(total * elapsed / game_round.reveal_duration_seconds))


def round_status(game_round):
    if game_round.outcome in COMPLETED:
        return game_round.outcome
    if (
        game_round.match.status == Match.Status.ABANDONED
        or game_round.outcome == Round.Outcome.EXPIRED
    ):
        return "expired"
    return "active" if game_round.reveal_started_at else "pending"


def snapshot(game_round, now=None):
    now = now or timezone.now()
    expire_round(game_round, now)
    state = round_status(game_round)
    count = revealed_count(game_round, now)
    points = game_round.player_states.values_list("score", flat=True).first() or 0
    result = {
        "id": str(game_round.pk),
        "number": game_round.number,
        "status": state,
        "server_now": now.isoformat(),
        "started_at": game_round.reveal_started_at.isoformat()
        if game_round.reveal_started_at
        else None,
        "reveal_finishes_at": (
            game_round.reveal_started_at + timedelta(seconds=game_round.reveal_duration_seconds)
        ).isoformat()
        if game_round.reveal_started_at
        else None,
        "expires_at": game_round.expires_at.isoformat() if game_round.expires_at else None,
        "reveal_duration_seconds": game_round.reveal_duration_seconds,
        "grid_size": game_round.grid_size,
        "revealed_count": count,
        "total_tiles": game_round.grid_size**2,
        "revealed_tiles": game_round.reveal_order[:count],
        "guess_count": game_round.guesses.count(),
        "score": points,
        "available_points": score_for_reveal(count, game_round.grid_size**2)
        if state == "active"
        else 0,
        "can_forfeit": state == "active" and count == game_round.grid_size**2,
        "image_url": f"/api/games/singleplayer/rounds/{game_round.pk}/image/?v={count}"
        if state in {"active", *COMPLETED}
        else None,
        "completion": None,
    }
    if state in COMPLETED:
        result["completion"] = {
            "answer": game_round.answer_snapshot,
            "outcome": state,
            "score": points,
            "solved_in_seconds": round(
                (game_round.ended_at - game_round.reveal_started_at).total_seconds(), 2
            )
            if state == "solved"
            else None,
            "guesses": result["guess_count"],
            "license": game_round.image.license,
            "attribution": game_round.image.attribution,
            "category": game_round.image.category.name,
        }
    return result


def session_snapshot(request, game_round, now):
    match = game_round.match
    participant = participant_for(request, game_round)
    rounds = list(match.rounds.order_by("number").prefetch_related("player_states"))
    current = latest_started_round(match)
    history = []
    for item in rounds:
        state = round_status(item)
        result = {"number": item.number, "outcome": state, "score": None}
        if item.outcome in COMPLETED:
            result.update(
                score=next(
                    (
                        state.score
                        for state in item.player_states.all()
                        if state.participant_id == participant.pk
                    ),
                    0,
                ),
                answer=item.answer_snapshot,
            )
        history.append(result)
    return {
        "id": str(match.pk),
        "revision": match.singleplayer_revision,
        "status": "complete"
        if match.status == Match.Status.COMPLETE
        else "expired"
        if match.status == Match.Status.ABANDONED
        else "active",
        "server_now": now.isoformat(),
        "expires_at": match.singleplayer_expires_at.isoformat()
        if match.singleplayer_expires_at
        else None,
        "total_rounds": match.singleplayer_round_limit,
        "current_round_number": current.number if current else 1,
        "total_score": participant.total_score,
        "max_score": match.singleplayer_round_limit * 1000,
        "solved_rounds": sum(item.outcome == Round.Outcome.SOLVED for item in rounds),
        "rounds": history,
    }


def state_payload(request, game_round, now=None, **extra):
    now = now or timezone.now()
    data = snapshot(game_round, now)
    return {"round": data, "session": session_snapshot(request, game_round, now), **extra}


def current_game(request):
    round_id = request.session.get(CURRENT_KEY)
    game_round = owned_rounds(request).filter(pk=round_id).first() if round_id else None
    # A late retry of an older completed game must not hide an unfinished game.
    active = (
        owned_rounds(request)
        .filter(
            match__singleplayer_round_limit=ROUND_LIMIT,
            match__status=Match.Status.ACTIVE,
            number=1,
        )
        .order_by("-match__created_at")
        .first()
    )
    if active:
        game_round = active
    if not game_round or game_round.match.singleplayer_round_limit != ROUND_LIMIT:
        return {"round": None, "session": None}
    return state_payload(request, latest_started_round(game_round.match))


def lock_round(request, round_id, match_id):
    Match.objects.filter(pk=match_id).update(status=F("status"))
    game_round = owned_round(request, round_id)
    if game_round.match.singleplayer_round_limit != ROUND_LIMIT:
        raise GameError(
            "Previous one-round games are read-only. Start a new game.", "legacy_session", 410
        )
    expire_round(game_round, timezone.now())
    return game_round


def invalid_state(request, game_round, now):
    if game_round.outcome in COMPLETED:
        current = latest_started_round(game_round.match)
        return state_payload(request, current or game_round, now, result="already_completed")
    if game_round.match.status != Match.Status.ACTIVE:
        return state_payload(
            request,
            game_round,
            now,
            result="expired",
            detail="This game has expired. Start a new game.",
            code="round_expired",
        )
    current = latest_started_round(game_round.match)
    if not current or current.pk != game_round.pk:
        raise GameError("Only the current round can be played.", "round_not_current")
    return None


def bump_revision(match):
    Match.objects.filter(pk=match.pk).update(singleplayer_revision=F("singleplayer_revision") + 1)
    match.refresh_from_db(fields=["singleplayer_revision"])


def finish_round(game_round, participant, now, outcome, score):
    # Called only under the match writer lock after validating an unfinished round.
    game_round.outcome = outcome
    game_round.ended_at = now
    game_round.winner = participant if outcome == Round.Outcome.SOLVED else None
    game_round.save(update_fields=["outcome", "ended_at", "winner"])
    RoundPlayerState.objects.filter(round=game_round, participant=participant).update(
        score=score, solved_at=now if outcome == Round.Outcome.SOLVED else None
    )
    participant.total_score = (
        RoundPlayerState.objects.filter(participant=participant).aggregate(total=Sum("score"))[
            "total"
        ]
        or 0
    )
    participant.save(update_fields=["total_score"])
    if game_round.number == game_round.match.singleplayer_round_limit:
        game_round.match.status = Match.Status.COMPLETE
        game_round.match.completed_at = now
        game_round.match.save(update_fields=["status", "completed_at"])


def submit_guess(request, round_id, text, request_id):
    match_id = owned_round(request, round_id).match_id
    with transaction.atomic():
        game_round = lock_round(request, round_id, match_id)
        now = timezone.now()
        invalid = invalid_state(request, game_round, now)
        if invalid:
            return invalid
        previous = Guess.objects.filter(request_id=request_id).first()
        if previous:
            if previous.round_id != game_round.pk or normalize_guess(
                previous.text
            ) != normalize_guess(text):
                raise GameError("This request was used for another guess.", "request_conflict")
            return state_payload(
                request, game_round, now, result="correct" if previous.correct else "incorrect"
            )
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
            points = score_for_reveal(revealed_count(game_round, now), game_round.grid_size**2)
            finish_round(game_round, participant, now, Round.Outcome.SOLVED, points)
        bump_revision(game_round.match)
        return state_payload(request, game_round, now, result="correct" if correct else "incorrect")


def forfeit_round(request, round_id):
    match_id = owned_round(request, round_id).match_id
    with transaction.atomic():
        game_round = lock_round(request, round_id, match_id)
        now = timezone.now()
        invalid = invalid_state(request, game_round, now)
        if invalid:
            return invalid
        if revealed_count(game_round, now) != game_round.grid_size**2:
            raise GameError("Forfeit is available after the full reveal.", "reveal_incomplete")
        finish_round(
            game_round, participant_for(request, game_round), now, Round.Outcome.FORFEITED, 0
        )
        bump_revision(game_round.match)
        return state_payload(request, game_round, now, result="forfeited")


def next_round(request, round_id, request_id):
    match_id = owned_round(request, round_id).match_id
    with transaction.atomic():
        previous = lock_round(request, round_id, match_id)
        now = timezone.now()
        if previous.match.status == Match.Status.ABANDONED:
            return state_payload(
                request,
                previous,
                now,
                result="expired",
                detail="This game has expired.",
                code="round_expired",
            )
        if previous.outcome not in COMPLETED:
            raise GameError("Finish the current round first.", "round_unfinished")
        if previous.number == ROUND_LIMIT:
            return state_payload(request, previous, now, result="session_complete")
        existing = Round.objects.filter(start_request_id=request_id).first()
        if existing and (
            existing.match_id != previous.match_id or existing.number != previous.number + 1
        ):
            raise GameError("This request was used for another round.", "request_conflict")
        current = latest_started_round(previous.match)
        if current.number > previous.number:
            # Retrying an old transition must neither restart nor advance a round.
            request.session[CURRENT_KEY] = str(current.pk)
            return state_payload(request, current, now, result="resumed")
        target = previous.match.rounds.select_related("image").get(number=previous.number + 1)
        used = list(
            previous.match.rounds.filter(reveal_started_at__isnull=False)
            .order_by("number")
            .values_list("image_id", flat=True)
        )
        image = choose_image(approved_images(), used, used[-1], preferred=target.image_id)
        from .reveal import prepare_image

        prepare_image(image.image_file.name)
        # Only new, not-yet-started rounds can update their image/answer snapshot.
        for field, value in image_fields(image).items():
            setattr(target, field, value)
        target.start_request_id = request_id
        target.reveal_started_at = timezone.now()
        target.save(
            update_fields=[
                "image",
                "answer_snapshot",
                "synonyms_snapshot",
                "image_storage_name",
                "start_request_id",
                "reveal_started_at",
            ]
        )
        bump_revision(previous.match)
        request.session[CURRENT_KEY] = str(target.pk)
        return state_payload(
            request, owned_round(request, target.pk), target.reveal_started_at, result="started"
        )
