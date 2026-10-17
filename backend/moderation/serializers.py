from rest_framework import serializers

from .models import Report, Sanction


class ReportSerializer(serializers.ModelSerializer):
    details = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")

    def validate(self, attrs):
        if attrs.get("category") != "other" and not attrs.get("details", "").strip():
            raise serializers.ValidationError({"details": "This field is required."})
        return attrs

    class Meta:
        model = Report
        fields = ["id", "subject", "category", "details", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_subject(self, value):
        if value == self.context["request"].user:
            raise serializers.ValidationError("You cannot report yourself.")
        return value


class SanctionSerializer(serializers.ModelSerializer):
    reason = serializers.SerializerMethodField()

    def get_reason(self, obj):
        return obj.reason or "A moderation notice has been applied to your account."

    class Meta:
        model = Sanction
        fields = ["id", "category", "kind", "reason", "starts_at", "expires_at", "acknowledged_at"]
        read_only_fields = fields
