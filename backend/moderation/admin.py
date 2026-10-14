from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Activity, Report, Sanction


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("subject", "reporter", "category", "created_at", "resolved_at")
    list_filter = ("category", "resolved_at")
    readonly_fields = ("reporter", "subject", "category", "details", "created_at", "resolved_by")

    def has_add_permission(self, request):
        return False  # Report identity/content must come from the validated player API.

    def has_delete_permission(self, request, obj=None):
        return False  # Reports and their context are retained as moderation history.

    def save_model(self, request, obj, form, change):
        if (
            change
            and {"resolved_at", "resolution"}.intersection(form.changed_data)
            and obj.resolved_at
        ):
            obj.resolved_by = request.user
            obj.resolution = obj.resolution or "resolved"
            Activity.objects.create(
                user=obj.subject, actor=request.user, action="report_" + obj.resolution, report=obj
            )
        super().save_model(request, obj, form, change)


@admin.register(Sanction)
class SanctionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "category", "starts_at", "expires_at", "revoked_at")
    list_filter = ("kind", "category")
    readonly_fields = ("issued_by", "acknowledged_at", "revoked_at", "revoked_by", "replaces")
    actions = ["revoke"]

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(field.name for field in Sanction._meta.fields)
        return super().get_readonly_fields(request, obj)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.issued_by = request.user
            obj.save()

    @admin.action(
        description="Revoke selected sanctions (closure requires administrator)",
        permissions=["change"],
    )
    def revoke(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied("Sanction changes require change permission.")
        user_ids = sorted(set(queryset.values_list("user_id", flat=True)))
        with transaction.atomic():
            from accounts.models import User

            for user_id in user_ids:
                User.objects.filter(pk=user_id).update(
                    last_username_change=F("last_username_change")
                )
            # Lock before mutable reads, including on SQLite; repeat actions are no-ops.
            queryset.update(revoked_at=F("revoked_at"))
            if (
                not request.user.is_superuser
                and queryset.filter(kind=Sanction.Kind.CLOSED).exists()
            ):
                raise PermissionDenied("Only administrators can reverse closure.")
            for sanction in queryset.filter(revoked_at__isnull=True).order_by("pk"):
                sanction.revoked_at = timezone.now()
                sanction.revoked_by = request.user
                sanction.save(update_fields=["revoked_at", "revoked_by"])
                self.log_change(
                    request, sanction, f"Revoked {sanction.kind} for account {sanction.user_id}."
                )
