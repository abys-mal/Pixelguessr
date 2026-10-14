from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
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
    readonly_fields = ("rating", "ranked_tier")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields += ("is_staff", "is_superuser", "groups", "user_permissions")
        return fields

    def has_change_permission(self, request, obj=None):
        if obj and not request.user.is_superuser and (obj.is_staff or obj.is_superuser):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and not request.user.is_superuser and (obj.is_staff or obj.is_superuser):
            return False
        return super().has_delete_permission(request, obj)


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
