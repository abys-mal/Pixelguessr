from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "display_name", "ranked_tier", "title", "date_joined"]
        read_only_fields = fields

    def get_title(self, obj):
        title = getattr(obj, "verified_title", None)
        return title.title if title and not title.revoked_at else None


class PublicProfileSerializer(UserSerializer):
    class Meta(UserSerializer.Meta):
        fields = ["id", "username", "display_name", "ranked_tier", "title", "date_joined"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    class Meta:
        model = User
        fields = ["username", "email", "display_name", "password"]

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is unavailable.")
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate(self, attrs):
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
