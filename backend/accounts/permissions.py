from rest_framework.permissions import BasePermission


class AccountAccess(BasePermission):
    message = "Sign in with an account that can access this feature."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        from moderation.services import account_restrictions

        restrictions = account_restrictions(request.user)
        if restrictions["blocked"]:
            self.message = "Your account has been closed."
            return False
        return True


class CanSubmitImages(AccountAccess):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        from moderation.services import account_restrictions

        restrictions = account_restrictions(request.user)
        if restrictions["probation"] or restrictions["suspension"]:
            self.message = "Image submissions are unavailable during probation or suspension."
            return False
        return True
