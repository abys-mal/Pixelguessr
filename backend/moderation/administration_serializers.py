from collections.abc import Mapping

from rest_framework import serializers

from library.models import Category, validate_synonyms


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, Mapping) and set(data) - set(self.fields):
            raise serializers.ValidationError({"detail": "Unexpected fields."})
        return super().to_internal_value(data)


class PlayerAction(StrictInput):
    operation = serializers.ChoiceField(choices=["rating", "title", "reopen", "moderator"])
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    rating = serializers.IntegerField(required=False)
    title = serializers.ChoiceField(choices=["", "pro", "master", "legend"], required=False)
    enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        field = {"rating": "rating", "title": "title", "moderator": "enabled"}.get(
            attrs["operation"]
        )
        if field and field not in attrs:
            raise serializers.ValidationError({field: "This field is required."})
        return attrs


class AnnouncementInput(StrictInput):
    title = serializers.CharField(max_length=160, allow_blank=True)
    body = serializers.CharField(max_length=5000, allow_blank=True)
    published = serializers.BooleanField()
    expires_at = serializers.DateTimeField(allow_null=True)
    version = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        from django.utils import timezone

        if attrs["published"] and (not attrs["title"] or not attrs["body"]):
            raise serializers.ValidationError("Published announcements require a title and body.")
        if attrs["expires_at"] and attrs["expires_at"] <= timezone.now():
            raise serializers.ValidationError("Choose a future expiration.")
        return attrs


class ImageEdit(StrictInput):
    canonical_answer = serializers.CharField(max_length=120)
    accepted_synonyms = serializers.JSONField(validators=[validate_synonyms])
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())


class ImageAction(StrictInput):
    operation = serializers.ChoiceField(choices=["approve", "reject", "retire", "restore"])
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    reason = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


class BatchInput(StrictInput):
    name = serializers.CharField(max_length=120)
