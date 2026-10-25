from channels.db import database_sync_to_async

from .ip_rules import IPAccessDenied, enforce_scope


class IPAccessSocketMixin:
    async def check_ip_access(self, *, notify=False):
        if getattr(self, "ip_access_denied", False):
            return False
        try:
            await database_sync_to_async(enforce_scope)(self.scope, self.ip_activity)
        except IPAccessDenied as exc:
            self.ip_access_denied = True
            if notify:
                if exc.login_restricted and getattr(self, "ip_account_socket", False):
                    await self.send_json(
                        {"type": "state", "state": {"user": None, "restrictions": None}}
                    )
                await self.send_json(
                    {
                        "type": "access_denied",
                        "detail": str(exc.detail["detail"]),
                        "code": str(exc.detail["code"]),
                        "status": 403,
                    }
                )
            await self.close(code=4403)
            return False
        return True
