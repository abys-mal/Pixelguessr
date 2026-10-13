from collections.abc import Mapping

from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from games.ranked_rules import tier

from .models import User
from .validators import validate_username_rules


class UserSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    ranked_tier = serializers.SerializerMethodField()

    def get_ranked_tier(self, obj):
        return tier(obj.rating)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "display_name",
            "ranked_tier",
            "rating",
            "ranked_matches",
            "ranked_wins",
            "ranked_losses",
            "title",
            "date_joined",
        ]
        read_only_fields = fields

    def get_title(self, obj):
        title = getattr(obj, "verified_title", None)
        return title.title if title and not title.revoked_at else None


class PublicProfileSerializer(UserSerializer):
    class Meta(UserSerializer.Meta):
        fields = [
            "id",
            "username",
            "display_name",
            "ranked_tier",
            "rating",
            "ranked_matches",
            "ranked_wins",
            "ranked_losses",
            "title",
            "date_joined",
        ]
        read_only_fields = fields


def username_format(value):
    value = User.normalize_username(value)
    try:
        validate_username_rules(value)
        User._meta.get_field("username").run_validators(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc
    return value


def available_username(value, *, excluding=None):
    value = username_format(value)
    if User.objects.filter(username__iexact=value).exclude(pk=excluding).exists():
        raise serializers.ValidationError("This username is unavailable.")
    return value


def available_email(value, *, excluding=None):
    value = value.lower()
    if User.objects.filter(email__iexact=value).exclude(pk=excluding).exists():
        raise serializers.ValidationError("This email is already registered.")
    return value


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(max_length=150, trim_whitespace=False)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    class Meta:
        model = User
        fields = ["username", "email", "display_name", "password", "password_confirm"]

    def validate_username(self, value):
        return available_username(value)

    def validate_email(self, value):
        return available_email(value)

    def validate(self, attrs):
        confirmation = attrs.pop("password_confirm")
        if attrs["password"] != confirmation:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        try:
            password_validation.validate_password(
                attrs["password"], User(**{k: v for k, v in attrs.items() if k != "password"})
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        user = authenticate(request=self.context["request"], **attrs)
        if not user:
            raise serializers.ValidationError("Invalid username or password.")
        from moderation.services import account_restrictions

        if account_restrictions(user)["blocked"]:
            raise serializers.ValidationError("This account is suspended or closed.")
        return {"user": user}


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["display_name"]


class AccountChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"detail": "Unexpected account fields."})
        return super().to_internal_value(data)


class UsernameChangeSerializer(AccountChangeSerializer):
    new_username = serializers.CharField(max_length=150, trim_whitespace=False)

    def validate_new_username(self, value):
        return username_format(value)


class EmailChangeSerializer(AccountChangeSerializer):
    new_email = serializers.EmailField(max_length=254)


class PasswordChangeSerializer(AccountChangeSerializer):
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs
