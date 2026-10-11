from rest_framework import serializers


class StartRoundSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()


class GuessSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    guess = serializers.CharField(max_length=120, trim_whitespace=True)

    def validate_guess(self, value):
        from .services import normalize_guess

        if not normalize_guess(value):
            raise serializers.ValidationError("Enter a word or phrase, not just punctuation.")
        return value
