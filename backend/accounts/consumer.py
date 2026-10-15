"""Normal-session account updates, with periodic durable recovery across processes."""

import asyncio
from contextlib import suppress

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from games.party_consumer import live_request
from moderation.enforcement import account_group
from moderation.services import session_account

from .session_state import session_payload


def read_status(session_key):
    request = live_request(session_key)
    user = session_account(request.session)
    return (user.pk if user else None), session_payload(request)


class AccountConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        headers = dict(self.scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        host = headers.get(b"host", b"").decode()
        scheme = "https" if self.scope.get("scheme") == "wss" else "http"
        if origin not in [*settings.CSRF_TRUSTED_ORIGINS, f"{scheme}://{host}"]:
            await self.close(code=4403)
            return
        self.session_key = self.scope["session"].session_key
        user_id, payload = await database_sync_to_async(read_status)(self.session_key)
        if not user_id:
            await self.close(code=4403)
            return
        self.group = account_group(user_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        self.last_payload = None
        if not await self.push():
            return
        self.timer = asyncio.create_task(self.tick())

    async def push(self):
        user_id, payload = await database_sync_to_async(read_status)(self.session_key)
        if payload != self.last_payload:
            await self.send_json({"type": "state", "state": payload})
            self.last_payload = payload
        if not user_id or payload.get("account_closed"):
            await self.close(code=4403)
            return False
        return True

    async def tick(self):
        while True:
            await asyncio.sleep(1)
            if not await self.push():
                return

    async def account_changed(self, event):
        await self.push()

    async def disconnect(self, code):
        if hasattr(self, "timer"):
            self.timer.cancel()
            with suppress(asyncio.CancelledError):
                await self.timer
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
