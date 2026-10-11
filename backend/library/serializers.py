import warnings
from io import BytesIO
from urllib.parse import urlsplit

from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

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
        if upload.size > 8 * 1024 * 1024:
            raise serializers.ValidationError("Upload a JPEG, PNG, or WebP of at most 8 MB.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(upload) as image:
                    if (
                        image.format not in {"JPEG", "PNG", "WEBP"}
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise serializers.ValidationError(
                            "Only still JPEG, PNG, and WebP images are supported."
                        )
                    if (
                        min(image.size) < 64
                        or max(image.size) > 4096
                        or image.width * image.height > 12_000_000
                    ):
                        raise serializers.ValidationError(
                            "Image dimensions must be 64–4096 px, with at most 12 megapixels."
                        )
                    image.load()
                    # Re-encode to strip metadata, payloads, and descriptive filenames.
                    output = BytesIO()
                    image.convert("RGB").save(output, format="WEBP", quality=90)
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombWarning,
            Image.DecompressionBombError,
        ) as exc:
            raise serializers.ValidationError("The file is not a valid supported image.") from exc
        return ContentFile(output.getvalue(), name="image.webp")
