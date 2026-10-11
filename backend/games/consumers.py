from channels.generic.websocket import AsyncWebsocketConsumer


class UnavailableMatchConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Intentional rejection: routing is prepared, gameplay is not implemented.
        await self.close(code=4404)
