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
        return {
            "user": None,
            "restrictions": None,
            "account_closed": True,
            "closure_message": "Your account has been closed.",
        }
    return {"user": UserSerializer(user).data, "restrictions": restrictions}
