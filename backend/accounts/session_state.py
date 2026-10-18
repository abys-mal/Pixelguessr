from accounts.serializers import UserSerializer
from moderation.services import account_restrictions, session_account


def session_payload(request):
    user = request.user if request.user.is_authenticated else session_account(request.session)
    if not user:
        return {"user": None, "restrictions": None}
    restrictions = account_restrictions(user)
    if restrictions["blocked"]:
        from moderation.services import active_sanctions

        if not active_sanctions(user).filter(kind="closed").exists():
            return {"user": None, "restrictions": None}
        payload = {
            "user": None,
            "restrictions": None,
            "account_closed": True,
            "closure_message": "You voluntarily closed your account."
            if active_sanctions(user).filter(kind="closed", origin="voluntary").exists()
            else "Your account has been closed.",
        }
        # Consume the invalidated identity once, including for account sockets.
        # Later visits must be anonymous rather than repeating the closure banner.
        from django.contrib.auth import logout

        logout(request)
        return payload
    return {"user": UserSerializer(user).data, "restrictions": restrictions}
