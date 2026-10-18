from urllib.parse import urlsplit

from rest_framework import serializers

from .image_processing import convert_image
from .models import Category, ImageSubmission, validate_synonyms


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class PublicImageSerializer(serializers.ModelSerializer):
    # Explicit allowlist. Do not add answers, filenames, or source URLs here.
    category = CategorySerializer(read_only=True)

    class Meta:
        model = ImageSubmission
        fields = ["id", "category", "created_at"]
        read_only_fields = fields


class SubmissionSerializer(serializers.ModelSerializer):
    image_file = serializers.FileField(write_only=True, required=False)
    accepted_synonyms = serializers.JSONField(required=False, validators=[validate_synonyms])

    class Meta:
        model = ImageSubmission
        fields = [
            "id",
            "canonical_answer",
            "accepted_synonyms",
            "category",
            "source",
            "source_url",
            "external_image_url",
            "image_file",
            "license",
            "attribution",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]

    def validate(self, attrs):
        if bool(attrs.get("image_file")) == bool(attrs.get("external_image_url")):
            raise serializers.ValidationError(
                "Provide exactly one uploaded image or external image URL."
            )
        for field in ("source_url", "external_image_url"):
            if attrs.get(field):
                parsed = urlsplit(attrs[field])
                if parsed.scheme != "https" or parsed.username or parsed.password:
                    raise serializers.ValidationError(
                        {field: "Use an HTTPS URL without credentials."}
                    )
        # References are stored for staff review only; this server never fetches them.
        if attrs["source"] in ("commons", "licensed") and not attrs.get("source_url"):
            raise serializers.ValidationError(
                {"source_url": "This source requires a provenance URL."}
            )
        return attrs

    def validate_image_file(self, upload):
        return convert_image(upload).file


class ContributionInput(SubmissionSerializer):
    image_file = serializers.FileField(write_only=True, required=True)
    rights_acknowledged = serializers.BooleanField(write_only=True)

    class Meta(SubmissionSerializer.Meta):
        fields = [
            field for field in SubmissionSerializer.Meta.fields if field != "external_image_url"
        ] + ["rights_acknowledged"]

    def to_internal_value(self, data):
        if set(data) - set(self.fields) or set(data) & {"id", "status", "created_at"}:
            raise serializers.ValidationError({"detail": "Unexpected contribution fields."})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs.get("rights_acknowledged") is not True:
            raise serializers.ValidationError(
                {
                    "rights_acknowledged": "Confirm that you have permission to submit this image for use in the game."
                }
            )
        return super().validate(attrs)
