from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import User, VerifiedTitle
from .validators import validate_username_rules


class UsernameRulesMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].strip = False

    def clean_username(self):
        value = self.cleaned_data["username"]
        # Unrelated admin edits must not reject a legacy trailing separator.
        if self.instance._state.adding or value != self.instance.username:
            validate_username_rules(value)
        if User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This username is unavailable.")
        return value


class CustomUserCreationForm(UsernameRulesMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class CustomUserChangeForm(UsernameRulesMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


@admin.register(User)
class PixelUserAdmin(UserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    fieldsets = UserAdmin.fieldsets + (
        ("Pixelguessr", {"fields": ("display_name", "rating", "ranked_tier")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + ((None, {"fields": ("email",)}),)
    readonly_fields = ("rating", "ranked_tier", "is_staff", "is_superuser")

    def save_model(self, request, obj, form, change):
        previous = User.objects.filter(pk=obj.pk).first() if change else None
        if previous and obj.pk == request.user.pk and not obj.is_active:
            raise ValidationError("You cannot deactivate your own staff account.")
        if (
            previous
            and (previous.is_staff != obj.is_staff or previous.is_superuser != obj.is_superuser)
        ) or (not previous and (obj.is_staff or obj.is_superuser)):
            raise ValidationError("Administrator assignment and removal are command-line-only.")
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.is_staff or obj.is_superuser):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(models.Q(is_staff=True) | models.Q(is_superuser=True)).exists():
            raise ValidationError("Administrator and staff account removal is command-line-only.")
        super().delete_queryset(request, queryset)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj and obj.pk == request.user.pk:
            fields += ("is_active",)
        if not request.user.is_superuser:
            fields += ("is_staff", "is_superuser", "groups", "user_permissions")
        return fields

    def has_change_permission(self, request, obj=None):
        if obj and not request.user.is_superuser and (obj.is_staff or obj.is_superuser):
            return False
        return super().has_change_permission(request, obj)


admin.site.unregister(Group)


@admin.register(Group)
class AdministrativeGroupAdmin(GroupAdmin):
    # Group edits delegate permissions, so model permissions alone cannot authorize them.
    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)


@admin.register(VerifiedTitle)
class VerifiedTitleAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "verified_by", "verified_at", "revoked_at")
    readonly_fields = ("verified_by", "verified_at")

    def save_model(self, request, obj, form, change):
        if not change or {"title", "user"}.intersection(form.changed_data):
            obj.verified_by = request.user
            obj.verified_at = timezone.now()
        obj.full_clean()
        super().save_model(request, obj, form, change)
