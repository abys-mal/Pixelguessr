from rest_framework.permissions import BasePermission


class AccountAccess(BasePermission):
    message = "Sign in with an account that can access this feature."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        from moderation.services import account_restrictions

        restrictions = account_restrictions(request.user)
        if restrictions["blocked"]:
            self.message = "This account is suspended or closed."
            return False
        if restrictions["unacknowledged_warnings"]:
            self.message = "Acknowledge your account warning before continuing."
            return False
        return True


class CanSubmitImages(AccountAccess):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        from moderation.services import account_restrictions

        if account_restrictions(request.user)["probation"]:
            self.message = "Image submissions are disabled during probation."
            return False
        return True
