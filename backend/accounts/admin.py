from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import ValidationError

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


@admin.register(VerifiedTitle)
class VerifiedTitleAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "verified_by", "verified_at", "revoked_at")
    readonly_fields = ("verified_by", "verified_at")

    def save_model(self, request, obj, form, change):
        obj.verified_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
