from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response

from . import parties
from .party_serializers import (
    CreatePartySerializer,
    JoinPartySerializer,
    PartyActionSerializer,
    PartyGuessSerializer,
    PartyKickSerializer,
    PartySettingsSerializer,
)
from .reveal import render_reveal
from .singleplayer_views import SingleplayerView


@method_decorator(csrf_protect, name="dispatch")
class PartyCreateView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request):
        serializer = CreatePartySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        code = parties.create_party(request, serializer.validated_data)
        return Response(parties.party_state(request, code), status=201)


@method_decorator(csrf_protect, name="dispatch")
class PartyView(SingleplayerView):
    def get(self, request, code):
        # HTTP polling is also a presence fallback when WebSockets are unavailable.
        return Response(parties.party_state(request, code, heartbeat=True))

    def patch(self, request, code):
        serializer = PartySettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parties.settings_party(request, code, serializer.validated_data)
        return Response(parties.party_state(request, code))


@method_decorator(csrf_protect, name="dispatch")
class PartyJoinView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request, code):
        serializer = JoinPartySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        parties.join_party(request, code)
        return Response(parties.party_state(request, code))


@method_decorator(csrf_protect, name="dispatch")
class PartyActionView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request, code, action):
        if action == "leave":
            parties.leave_party(request, code)
            return Response(status=204)
        serializer = PartyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        handler = {"start": parties.start_party, "lobby": parties.lobby_party}[action]
        handler(request, code, serializer.validated_data["request_id"])
        return Response(parties.party_state(request, code))


@method_decorator(csrf_protect, name="dispatch")
class PartyGuessView(SingleplayerView):
    throttle_scope = "game_guess"

    def post(self, request, code):
        serializer = PartyGuessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = parties.submit_party_guess(
            request, code, data["round_id"], data["guess"], data["request_id"]
        )
        return Response({"state": parties.party_state(request, code), "result": result})


class PartyImageView(SingleplayerView):
    def get(self, request, code, pk):
        game_round, now, count = parties.party_image(request, code, pk)
        content, count = render_reveal(game_round, now, count=count)
        response = HttpResponse(content, content_type="image/webp")
        response["X-Revealed-Tiles"] = str(count)
        response["Content-Disposition"] = 'inline; filename="reveal.webp"'
        return response


@method_decorator(csrf_protect, name="dispatch")
class PartyKickView(SingleplayerView):
    throttle_scope = "game_start"

    def post(self, request, code):
        serializer = PartyKickSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        parties.kick_party(
            request, code, data["target_id"], data["prevent_rejoin"], data["request_id"]
        )
        return Response(parties.party_state(request, code))
