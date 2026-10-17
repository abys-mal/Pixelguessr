from collections.abc import Mapping

from rest_framework import serializers

from accounts.serializers import SettingsSerializer

from .models import Activity, Appeal, Category, Report, Sanction
from .permissions import is_moderator, is_protected
from .workspace import eligibility


class PlayerNamesInput(SettingsSerializer):
    username = serializers.CharField(max_length=150, trim_whitespace=False, required=False)

    class Meta(SettingsSerializer.Meta):
        fields = ["username", "display_name"]

    def to_internal_value(self, data):
        if isinstance(data, Mapping) and set(data) - set(self.fields):
            raise serializers.ValidationError({"detail": "Only player names can be edited here."})
        return super().to_internal_value(data)


class SanctionInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Sanction.Kind)
    category = serializers.ChoiceField(choices=Category, default="fair_play")
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    internal_note = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        from django.utils import timezone

        expiry = attrs["expires_at"]
        if expiry and expiry <= timezone.now():
            raise serializers.ValidationError("Expiry must be in the future.")
        if attrs["kind"] == "closed" and expiry:
            raise serializers.ValidationError("Account closure cannot expire.")
        return attrs


def player_summary(user):
    from accounts.identity import honorary_title

    protected = is_protected(user)
    return {
        "title": honorary_title(user),
        "id": str(user.pk),
        "username": user.username,
        "display_name": user.display_name,
        "date_joined": user.date_joined.isoformat(),
        "rating": user.rating,
        "is_active": user.is_active,
        "protected": protected,
        "can_remove_moderator": protected and not (user.is_staff or user.is_superuser),
        "moderator": is_moderator(user),
    }


class StaffSanction(serializers.ModelSerializer):
    state = serializers.SerializerMethodField()
    issued_by = serializers.CharField(source="issued_by.username")
    revoked_by = serializers.CharField(source="revoked_by.username", allow_null=True)
    active = serializers.SerializerMethodField()

    def get_active(self, obj):
        from django.utils import timezone

        now = timezone.now()
        return (
            not obj.revoked_at
            and obj.starts_at <= now
            and (not obj.expires_at or obj.expires_at > now)
        )

    def get_state(self, obj):
        from django.utils import timezone

        if obj.revoked_at:
            return "reversed"
        if obj.starts_at > timezone.now():
            return "scheduled"
        return "active" if self.get_active(obj) else "expired"

    class Meta:
        model = Sanction
        fields = [
            "id",
            "kind",
            "category",
            "reason",
            "internal_note",
            "starts_at",
            "expires_at",
            "acknowledged_at",
            "revoked_at",
            "issued_by",
            "revoked_by",
            "replaces",
            "active",
            "state",
        ]


class StaffReport(serializers.ModelSerializer):
    subject = serializers.SerializerMethodField()
    reporter = serializers.CharField(source="reporter.username")

    def get_subject(self, obj):
        return player_summary(obj.subject)

    class Meta:
        model = Report
        fields = [
            "id",
            "subject",
            "reporter",
            "category",
            "details",
            "created_at",
            "resolved_at",
            "resolution",
        ]


class StaffAppeal(serializers.ModelSerializer):
    player = serializers.SerializerMethodField()
    sanction = StaffSanction()

    def get_player(self, obj):
        return player_summary(obj.user)

    class Meta:
        model = Appeal
        fields = [
            "id",
            "player",
            "sanction",
            "kind",
            "explanation",
            "status",
            "created_at",
            "resolved_at",
        ]


class PlayerAppeal(serializers.ModelSerializer):
    class Meta:
        model = Appeal
        fields = ["id", "sanction", "kind", "explanation", "status", "created_at", "resolved_at"]


class PlayerNotice(serializers.ModelSerializer):
    active = serializers.SerializerMethodField()

    def get_active(self, obj):
        from .services import active_sanctions

        return active_sanctions(obj.user).filter(pk=obj.pk).exists()

    appeal = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()

    def get_appeal(self, obj):
        return eligibility(obj.user, obj)

    def get_reason(self, obj):
        return obj.reason or "A moderation notice has been applied to your account."

    class Meta:
        model = Sanction
        fields = [
            "id",
            "kind",
            "category",
            "reason",
            "starts_at",
            "expires_at",
            "revoked_at",
            "acknowledged_at",
            "appeal",
            "active",
        ]


class StaffActivity(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username")

    class Meta:
        model = Activity
        fields = ["id", "actor", "action", "created_at", "sanction", "report", "appeal", "changes"]
