"""Session-scoped state stream and private guess acknowledgements."""

import asyncio
from contextlib import suppress
from importlib import import_module
from types import SimpleNamespace

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user
from rest_framework.exceptions import APIException

from moderation.ip_socket import IPAccessSocketMixin

from .parties import group_name, party_state, submit_party_guess
from .party_serializers import PartyGuessSerializer


def live_request(session_key):
    session = import_module(settings.SESSION_ENGINE).SessionStore(session_key=session_key)
    request = SimpleNamespace(session=session)
    request.user = get_user(request)
    return request


def socket_state(session_key, code, heartbeat=False):
    return party_state(live_request(session_key), code, heartbeat=heartbeat)


def socket_guess(session_key, code, round_id, text, request_id):
    return submit_party_guess(live_request(session_key), code, round_id, text, request_id)


class PartyConsumer(IPAccessSocketMixin, AsyncJsonWebsocketConsumer):
    ip_activity = "parties"

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or len(text_data or "") > 2048:
            await self.close(code=1009)
            return
        try:
            await super().receive(text_data=text_data, **kwargs)
        except ValueError:
            await self.close(code=1007)

    async def connect(self):
        headers = dict(self.scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        host = headers.get(b"host", b"").decode()
        scheme = "https" if self.scope.get("scheme") == "wss" else "http"
        if origin not in [*settings.CSRF_TRUSTED_ORIGINS, f"{scheme}://{host}"]:
            await self.close(code=4403)
            return
        if not await self.check_ip_access():
            return
        self.code = self.scope["url_route"]["kwargs"]["code"].upper()
        self.session_key = self.scope["session"].session_key
        try:
            state = await database_sync_to_async(socket_state)(
                self.session_key, self.code, heartbeat=True
            )
        except APIException:
            await self.close(code=4403)
            return
        self.group = group_name(self.code)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "state", "state": state})
        self.timer = asyncio.create_task(self.tick())
        self.last_heartbeat = asyncio.get_running_loop().time()

    async def disconnect(self, code):
        if hasattr(self, "timer"):
            self.timer.cancel()
            with suppress(asyncio.CancelledError):
                await self.timer
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
        # A durable 15s presence lease handles lost transport and multiple open tabs.

    async def push_state(self, heartbeat=False):
        if not await self.check_ip_access(notify=True):
            return False
        try:
            state = await database_sync_to_async(socket_state)(
                self.session_key, self.code, heartbeat=heartbeat
            )
        except APIException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
            await self.send_json(
                {
                    "type": "access_denied",
                    "detail": str(detail.get("detail", "This party is unavailable.")),
                    "code": str(detail.get("code", "party_access_denied")),
                    "status": exc.status_code,
                }
            )
            await self.close(code=4403)
            return False
        await self.send_json({"type": "state", "state": state})
        return True

    async def tick(self):
        while True:
            await asyncio.sleep(1)
            if not await self.push_state():
                return

    async def party_changed(self, event):
        await self.push_state()

    async def receive_json(self, content, **kwargs):
        if not await self.check_ip_access(notify=True):
            return
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "detail": "Send a JSON object."})
            return
        if content.get("type") == "heartbeat":
            # Bound client traffic; a refresh cannot remove a database cooldown.
            now = asyncio.get_running_loop().time()
            if now - self.last_heartbeat >= 3:
                self.last_heartbeat = now
                await self.push_state(heartbeat=True)
            return
        if content.get("type") != "guess":
            await self.send_json({"type": "error", "detail": "Unsupported party action."})
            return
        serializer = PartyGuessSerializer(data=content)
        request_id = content.get("request_id")
        try:
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            result = await database_sync_to_async(socket_guess)(
                self.session_key, self.code, data["round_id"], data["guess"], data["request_id"]
            )
            state = await database_sync_to_async(socket_state)(self.session_key, self.code)
            await self.send_json(
                {"type": "guess_result", "request_id": request_id, "result": result, "state": state}
            )
        except APIException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
            await self.send_json(
                {
                    "type": "error",
                    "request_id": request_id,
                    "detail": str(detail.get("detail", "Enter a valid guess.")),
                    "code": str(detail.get("code", "invalid_guess")),
                    "status": exc.status_code,
                }
            )
            await self.push_state()
