from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import Report, Sanction


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("subject", "reporter", "category", "created_at", "resolved_at")
    list_filter = ("category", "resolved_at")
    readonly_fields = ("reporter", "subject", "category", "details", "created_at")


@admin.register(Sanction)
class SanctionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "category", "starts_at", "expires_at", "revoked_at")
    list_filter = ("kind", "category")
    readonly_fields = ("issued_by", "acknowledged_at", "revoked_at", "revoked_by")
    actions = ["revoke"]

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(field.name for field in Sanction._meta.fields)
        return super().get_readonly_fields(request, obj)

    def save_model(self, request, obj, form, change):
        obj.issued_by = request.user
        obj.save()

    @admin.action(description="Revoke selected sanctions (closure requires administrator)")
    def revoke(self, request, queryset):
        if not request.user.is_superuser and queryset.filter(kind=Sanction.Kind.CLOSED).exists():
            raise PermissionDenied("Only administrators can reverse closure.")
        for sanction in queryset.filter(revoked_at__isnull=True):
            sanction.revoked_at = timezone.now()
            sanction.revoked_by = request.user
            sanction.save()
