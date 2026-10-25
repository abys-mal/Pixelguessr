from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError


class AdministratorLoginForm(AdminAuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser or not user.is_staff:
            raise ValidationError("Administrator access is required.", code="invalid_login")
        from moderation.ip_rules import IPAccessDenied, enforce_request

        try:
            enforce_request(self.request, "login", user=user)
        except IPAccessDenied as exc:
            raise ValidationError(str(exc.detail["detail"]), code=str(exc.detail["code"])) from exc


class AdministratorSite(AdminSite):
    login_form = AdministratorLoginForm

    def has_permission(self, request):
        from moderation.permissions import is_administrator

        return is_administrator(request.user)
