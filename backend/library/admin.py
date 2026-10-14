from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.html import format_html

from .models import Category, ImageSubmission
from .review import review_images

admin.site.register(Category)


@admin.register(ImageSubmission)
class ImageSubmissionAdmin(admin.ModelAdmin):
    list_display = ("id", "canonical_answer", "category", "status", "created_at")
    list_filter = ("status", "category", "source")
    search_fields = ("canonical_answer",)
    readonly_fields = (
        "submitted_by",
        "image_file",
        "private_preview",
        "created_at",
        "reviewed_by",
        "reviewed_at",
    )
    actions = ["approve", "reject"]

    @admin.display(description="Private image preview")
    def private_preview(self, obj):
        if not obj.image_file:
            return "External reference: inspect the external image URL above."
        return format_html(
            '<a href="/api/library/submissions/{}/preview/" target="_blank" rel="noopener">View private upload</a>',
            obj.pk,
        )

    def has_add_permission(self, request):
        return False  # All submissions use the validated API path.

    def save_model(self, request, obj, form, change):
        if obj.status != ImageSubmission.Status.PENDING:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        obj.full_clean()
        super().save_model(request, obj, form, change)

    def review(self, request, queryset, status):
        if not self.has_change_permission(request):
            raise PermissionDenied("Image review requires change permission.")
        with transaction.atomic():
            queryset.update(status=F("status"))
            review_images(queryset, request.user, status)
            for image in queryset:
                self.log_change(request, image, f"Reviewed submission: {status}.")

    @admin.action(description="Approve selected submissions", permissions=["change"])
    def approve(self, request, queryset):
        self.review(request, queryset, ImageSubmission.Status.APPROVED)

    @admin.action(description="Reject selected submissions", permissions=["change"])
    def reject(self, request, queryset):
        self.review(request, queryset, ImageSubmission.Status.REJECTED)
