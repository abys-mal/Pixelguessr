from django.http import HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .reveal import render_reveal
from .serializers import GuessSerializer, StartRoundSerializer
from .services import (
    GameError,
    current_game,
    expire_round,
    forfeit_round,
    next_round,
    owned_round,
    start_round,
    state_payload,
    submit_guess,
)


class SingleplayerView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "game_read"

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["Vary"] = "Cookie"
        return response


class CurrentRoundView(SingleplayerView):
    def get(self, request):
        return Response(current_game(request))


@method_decorator(csrf_protect, name="dispatch")
class StartRoundView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request):
        serializer = StartRoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        game_round = start_round(request, serializer.validated_data["request_id"])
        return Response(state_payload(request, game_round), status=201)


class RoundView(SingleplayerView):
    def get(self, request, pk):
        return Response(state_payload(request, owned_round(request, pk)))


@method_decorator(csrf_protect, name="dispatch")
class GuessView(SingleplayerView):
    throttle_scope = "game_guess"

    def post(self, request, pk):
        serializer = GuessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = submit_guess(request, pk, data["guess"], data["request_id"])
        return Response(result, status=410 if result["result"] == "expired" else 200)


class ImageView(SingleplayerView):
    def get(self, request, pk):
        game_round = owned_round(request, pk)
        now = timezone.now()
        expire_round(game_round, now)
        if game_round.match.status == "abandoned":
            raise GameError("This round has expired. Start a new picture.", "round_expired", 410)
        if not game_round.reveal_started_at:
            raise GameError("This round has not started.", "round_not_started")
        content, count = render_reveal(game_round, now)
        response = HttpResponse(content, content_type="image/webp")
        response["X-Revealed-Tiles"] = str(count)
        response["Content-Disposition"] = 'inline; filename="reveal.webp"'
        return response


@method_decorator(csrf_protect, name="dispatch")
class ForfeitView(SingleplayerView):
    throttle_scope = "game_guess"

    def post(self, request, pk):
        # Completion itself is the idempotency guard; no repeated forfeits can score.
        result = forfeit_round(request, pk)
        return Response(result, status=410 if result["result"] == "expired" else 200)


@method_decorator(csrf_protect, name="dispatch")
class NextRoundView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request, pk):
        serializer = StartRoundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = next_round(request, pk, serializer.validated_data["request_id"])
        return Response(result, status=410 if result["result"] == "expired" else 200)
