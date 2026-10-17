from threading import Lock

from django.core.cache import cache
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import User

from . import ranked
from .models import Match, Participant
from .party_serializers import PartyGuessSerializer
from .ranked_rules import rule, tier
from .reveal import render_reveal
from .serializers import StartRoundSerializer
from .singleplayer_views import SingleplayerView

# Bounded process-local locks coalesce simultaneous requests for the same frame.
# Redis remains the shared cache in deployment; permissions are checked before locking.
_frame_locks = [Lock() for _ in range(64)]


class RankedView(SingleplayerView):
    permission_classes = [IsAuthenticated]


@method_decorator(csrf_protect, name="dispatch")
class QueueView(RankedView):
    def get(self, request):
        return Response(ranked.queue_state(request.user))

    def post(self, request):
        serializer = StartRoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            ranked.queue_join(request.user, serializer.validated_data["request_id"]), status=201
        )


@method_decorator(csrf_protect, name="dispatch")
class CancelQueueView(RankedView):
    def post(self, request):
        serializer = StartRoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            ranked.queue_state(request.user, serializer.validated_data["request_id"], cancel=True)
        )


class RankedMatchView(RankedView):
    def get(self, request, match_id):
        return Response(ranked.state(request.user, match_id))


@method_decorator(csrf_protect, name="dispatch")
class RankedGuessView(RankedView):
    throttle_scope = "game_guess"

    def post(self, request, match_id):
        serializer = PartyGuessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            ranked.submit(
                request.user, match_id, data["round_id"], data["guess"], data["request_id"]
            )
        )


@method_decorator(csrf_protect, name="dispatch")
class RankedLeaveView(RankedView):
    def post(self, request, match_id):
        return Response(ranked.leave(request.user, match_id))


class RankedImageView(RankedView):
    def get(self, request, match_id, round_id):
        game_round, now, count = ranked.image(request.user, match_id, round_id)
        requested = request.query_params.get("v")
        if requested is not None:
            try:
                requested = int(requested)
            except (ValueError, TypeError) as exc:
                raise ValidationError("Invalid reveal frame.") from exc
            if requested < 0 or requested > count:
                raise ValidationError("This reveal frame is not available yet.")
            count = requested
        # Authorization/reconciliation above always precedes even a cache hit.
        key = f"ranked-frame:v1:{game_round.pk}:{count}"
        with _frame_locks[hash(key) % len(_frame_locks)]:
            content = cache.get(key)
            if content is None:
                content, count = render_reveal(game_round, now, count=count)
                cache.set(key, content, timeout=60)
        response = HttpResponse(content, content_type="image/webp")
        response["X-Revealed-Tiles"] = str(count)
        response["Content-Disposition"] = 'inline; filename="reveal.webp"'
        return response


class PublicRankedView(SingleplayerView):
    permission_classes = [AllowAny]


class LeaderboardView(PublicRankedView):
    def get(self, request):
        from accounts.identity import honorary_title

        users = (
            User.objects.filter(is_active=True, ranked_matches__gte=1)
            .annotate(sort_name=Lower("username"))
            .order_by("-rating", "sort_name", "id")
        )
        pagination = PageNumberPagination()
        page = pagination.paginate_queryset(users, request, view=self)
        start = pagination.page.start_index()
        response = pagination.get_paginated_response(
            [
                {
                    "position": start + index,
                    "username": user.username,
                    "title": honorary_title(user),
                    "rating": user.rating,
                    "tier": tier(user.rating),
                }
                for index, user in enumerate(page)
            ]
        )
        me = users.filter(pk=request.user.pk).first() if request.user.is_authenticated else None
        response.data["my_position"] = (
            1
            + users.filter(
                Q(rating__gt=me.rating)
                | Q(rating=me.rating, sort_name__lt=me.sort_name)
                | Q(rating=me.rating, sort_name=me.sort_name, pk__lt=me.pk)
            ).count()
            if me
            else None
        )
        response.data["tiers"] = rule("tiers")
        response.data["starting_elo"] = rule("starting_elo")
        return response


class HistoryView(PublicRankedView):
    def get(self, request, username):
        from accounts.identity import honorary_title

        user = get_object_or_404(User, username=username, is_active=True)
        entries = (
            Participant.objects.filter(
                user=user,
                match__mode=Match.Mode.RANKED,
                match__status=Match.Status.COMPLETE,
                rating_before__isnull=False,
            )
            .select_related("match")
            .prefetch_related("match__participants__user__verified_title")
            .order_by("-match__completed_at", "-match_id")
        )
        pagination = PageNumberPagination()
        page = pagination.paginate_queryset(entries, request, view=self)
        result = []
        for entry in page:
            opponent = next(p for p in entry.match.participants.all() if p.pk != entry.pk)
            result.append(
                {
                    "id": str(entry.match_id),
                    "date": entry.match.completed_at.isoformat(),
                    "opponent": opponent.user.username if opponent.user else "Deleted player",
                    "opponent_deleted": opponent.identity_deleted,
                    "opponent_title": honorary_title(opponent.user),
                    "outcome": "no_contest"
                    if entry.match.ranked_outcome == "no_contest"
                    else "win"
                    if entry.match.ranked_winner_id == entry.pk
                    else "loss",
                    "forfeit": entry.match.ranked_outcome == "forfeit",
                    "score": entry.decisive_wins,
                    "opponent_score": opponent.decisive_wins,
                    "rating_before": entry.rating_before,
                    "rating_after": entry.rating_after,
                    "rating_delta": entry.rating_delta,
                }
            )
        return pagination.get_paginated_response(result)
