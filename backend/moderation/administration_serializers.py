from collections.abc import Mapping

from rest_framework import serializers

from library.models import Category, ImageSubmission, validate_synonyms


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
    canonical_answer = serializers.CharField(max_length=120, required=False)
    accepted_synonyms = serializers.JSONField(validators=[validate_synonyms], required=False)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False)
    license = serializers.CharField(max_length=160, required=False)
    attribution = serializers.CharField(max_length=500, required=False)
    source = serializers.ChoiceField(choices=ImageSubmission.Source, required=False)
    source_url = serializers.URLField(max_length=1000, required=False, allow_blank=True)
    photographer = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ImportUpload(StrictInput):
    request_id = serializers.UUIDField()
    file = serializers.FileField()
    source = serializers.ChoiceField(
        choices=ImageSubmission.Source, required=False, default="manual"
    )
    license = serializers.CharField(max_length=160, required=False, allow_blank=True)
    attribution = serializers.CharField(max_length=500, required=False, allow_blank=True)
    source_url = serializers.URLField(max_length=1000, required=False, allow_blank=True)
    photographer = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ContributionReview(StrictInput):
    operation = serializers.ChoiceField(choices=["approve", "reject", "remove"])
    corrections = ImageEdit(required=False)
    explanation = serializers.CharField(
        max_length=2000, allow_blank=True, required=False, default=""
    )
    visible_to_player = serializers.BooleanField(default=False)
    confirm = serializers.BooleanField(default=False)


class ImageAction(StrictInput):
    operation = serializers.ChoiceField(choices=["approve", "reject", "retire", "restore"])
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    reason = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


class BatchInput(StrictInput):
    name = serializers.CharField(max_length=120)


class PermanentDeletionInput(StrictInput):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    reason = serializers.CharField(max_length=2000)
    confirmation = serializers.CharField(trim_whitespace=False, max_length=150)


class ImageDeletionInput(StrictInput):
    confirm = serializers.BooleanField()
