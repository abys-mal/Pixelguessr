from collections.abc import Mapping

from rest_framework import serializers

from .parties import guest_name
from .serializers import GuessSerializer, StartRoundSerializer


class PartySettingsSerializer(serializers.Serializer):
    reveal_seconds = serializers.ChoiceField(choices=[15, 30, 45, 60], required=False)
    round_limit = serializers.ChoiceField(choices=[5, 10, 15, 20], required=False)

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"detail": "Only reveal duration and round count can be configured."}
            )
        return super().to_internal_value(data)


class JoinPartySerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=40, required=False, default="")

    def validate_display_name(self, value):
        request = self.context["request"]
        return value if request.user.is_authenticated else guest_name(value)


class CreatePartySerializer(PartySettingsSerializer):
    request_id = serializers.UUIDField()
    display_name = serializers.CharField(max_length=40, required=False, default="")

    def validate_display_name(self, value):
        request = self.context["request"]
        return value if request.user.is_authenticated else guest_name(value)


class PartyGuessSerializer(GuessSerializer):
    round_id = serializers.UUIDField()


PartyActionSerializer = StartRoundSerializer
