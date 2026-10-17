from rest_framework.permissions import BasePermission


def is_administrator(user):
    return bool(user.is_authenticated and user.is_active and user.is_staff and user.is_superuser)


def is_moderator(user):
    if getattr(user, "is_superuser", False):
        return is_administrator(user)
    return bool(
        user.is_authenticated and user.is_active and user.has_perm("moderation.access_workspace")
    )


def is_protected(user):
    # Role assignments protect the account even while inactive or suspended.
    return bool(
        user.is_staff
        or user.is_superuser
        or user.user_permissions.filter(
            content_type__app_label="moderation", codename="access_workspace"
        ).exists()
        or user.groups.filter(
            permissions__content_type__app_label="moderation",
            permissions__codename="access_workspace",
        ).exists()
    )


class WorkspaceAccess(BasePermission):
    message = "Moderator access is required."

    def has_permission(self, request, view):
        from .services import account_restrictions

        return is_moderator(request.user) and not account_restrictions(request.user)["blocked"]


class AdministratorAccess(WorkspaceAccess):
    message = "Administrator access is required."

    def has_permission(self, request, view):
        return is_administrator(request.user) and super().has_permission(request, view)
