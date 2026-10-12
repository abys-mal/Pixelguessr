"""Authenticated ranked sockets; durable connection rows support multiple workers/tabs."""

import asyncio
import uuid
from contextlib import suppress

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from rest_framework.exceptions import APIException

from . import ranked
from .party_consumer import live_request
from .party_serializers import PartyGuessSerializer


class RankedConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        headers = dict(self.scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        host = headers.get(b"host", b"").decode()
        scheme = "https" if self.scope.get("scheme") == "wss" else "http"
        if origin not in [*settings.CSRF_TRUSTED_ORIGINS, f"{scheme}://{host}"]:
            await self.close(code=4403)
            return
        self.session_key = self.scope["session"].session_key
        self.connection_id = uuid.uuid4()
        self.match_id = self.scope["url_route"]["kwargs"].get("match_id")
        self.ticket = self.scope["url_route"]["kwargs"].get("ticket")
        try:
            state = await database_sync_to_async(self.read)(connect=True)
        except APIException:
            await self.close(code=4403)
            return
        await self.accept()
        await self.send_json({"type": "state", "state": state})
        self.last_heartbeat = asyncio.get_running_loop().time()
        self.last_message = 0
        self.timer = asyncio.create_task(self.tick())

    def read(self, heartbeat=False, connect=False):
        request = live_request(self.session_key)
        if self.match_id:
            return ranked.state(
                request.user,
                self.match_id,
                connection_id=self.connection_id,
                heartbeat=heartbeat or connect,
            )
        if connect:
            return ranked.queue_connect(request.user, self.ticket, self.connection_id)
        return ranked.queue_state(
            request.user, self.ticket, heartbeat=heartbeat, connection_id=self.connection_id
        )

    async def push(self, heartbeat=False):
        try:
            state = await database_sync_to_async(self.read)(heartbeat=heartbeat)
        except APIException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
            await self.send_json(
                {
                    "type": "access_denied",
                    "detail": str(detail.get("detail", "Ranked Duel is unavailable.")),
                    "code": str(detail.get("code", "access_denied")),
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
            if not await self.push():
                return

    async def disconnect(self, code):
        if hasattr(self, "timer"):
            self.timer.cancel()
            with suppress(asyncio.CancelledError):
                await self.timer
        if hasattr(self, "connection_id"):
            await database_sync_to_async(ranked.disconnect)(self.connection_id)

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or len(text_data or "") > 2048:
            await self.close(code=1009)
            return
        try:
            await super().receive(text_data=text_data, **kwargs)
        except ValueError:
            await self.close(code=1007)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "detail": "Send a JSON object."})
            return
        now = asyncio.get_running_loop().time()
        if content.get("type") == "heartbeat":
            if now - self.last_heartbeat >= 3:
                self.last_heartbeat = now
                await self.push(heartbeat=True)
            return
        if content.get("type") != "guess" or not self.match_id:
            await self.send_json({"type": "error", "detail": "Unsupported ranked action."})
            return
        # Bound malformed/spam traffic; normal one-guess gameplay never reaches this guard.
        if now - self.last_message < 0.1:
            return
        self.last_message = now
        try:
            serializer = PartyGuessSerializer(data=content)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            request = await database_sync_to_async(live_request)(self.session_key)
            result = await database_sync_to_async(ranked.submit)(
                request.user, self.match_id, data["round_id"], data["guess"], data["request_id"]
            )
            await self.send_json(
                {"type": "guess_result", "request_id": str(data["request_id"]), **result}
            )
        except APIException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"detail": str(exc.detail)}
            await self.send_json(
                {
                    "type": "error",
                    "request_id": str(content.get("request_id", "")),
                    "detail": str(detail.get("detail", "Enter a valid guess.")),
                    "code": str(detail.get("code", "invalid_guess")),
                    "status": exc.status_code,
                }
            )
            await self.push()
