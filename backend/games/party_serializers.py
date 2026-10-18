from collections.abc import Mapping

from rest_framework import serializers

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
    # Legacy supplied names are ignored; all guest names are server generated.
    automatic = serializers.BooleanField(default=False)


class CreatePartySerializer(PartySettingsSerializer):
    request_id = serializers.UUIDField()
    display_name = serializers.CharField(required=False, write_only=True, allow_blank=True)


class PartyKickSerializer(serializers.Serializer):
    target_id = serializers.UUIDField()
    prevent_rejoin = serializers.BooleanField(default=False)
    request_id = serializers.UUIDField()


class PartyGuessSerializer(GuessSerializer):
    round_id = serializers.UUIDField()


PartyActionSerializer = StartRoundSerializer


class PartyNextSerializer(StartRoundSerializer):
    round_id = serializers.UUIDField()
