"""Shared private-upload validation and metadata-free WebP encoding."""

import hashlib
import math
import warnings
from dataclasses import dataclass
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_BYTES = 8 * 1024 * 1024
MAX_EDGE = 4096
MAX_PIXELS = 12_000_000


@dataclass
class ConvertedImage:
    file: ContentFile
    digest: str
    original_size: tuple[int, int]
    size: tuple[int, int]


def convert_image(upload, *, resize=False, jpeg_only=False):
    if upload.size > MAX_BYTES:
        raise ValidationError("Upload a JPEG, PNG, or WebP of at most 8 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as original:
                if (
                    original.format not in ({"JPEG"} if jpeg_only else {"JPEG", "PNG", "WEBP"})
                    or getattr(original, "n_frames", 1) != 1
                ):
                    raise ValidationError(
                        "Local imports require still JPEG photographs."
                        if jpeg_only
                        else "Only still JPEG, PNG, and WebP images are supported."
                    )
                # Preserve the HTTP upload guard before allocating decoded pixel buffers.
                if not resize and (
                    min(original.size) < 64
                    or max(original.size) > MAX_EDGE
                    or original.width * original.height > MAX_PIXELS
                ):
                    raise ValidationError(
                        "Image dimensions must be 64–4096 px, with at most 12 megapixels."
                    )
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGB")
                try:
                    original_size = image.size
                    if resize:
                        scale = min(
                            1,
                            MAX_EDGE / image.width,
                            MAX_EDGE / image.height,
                            math.sqrt(MAX_PIXELS / (image.width * image.height)),
                        )
                        if scale < 1:
                            image.thumbnail(
                                (int(image.width * scale), int(image.height * scale)),
                                Image.Resampling.LANCZOS,
                            )
                    if (
                        min(image.size) < 64
                        or max(image.size) > MAX_EDGE
                        or image.width * image.height > MAX_PIXELS
                    ):
                        raise ValidationError(
                            "Image dimensions must be 64–4096 px, with at most 12 megapixels."
                        )
                    pixels = image.tobytes()
                    digest = hashlib.sha256(
                        f"RGB:{image.width}:{image.height}:".encode() + pixels
                    ).hexdigest()
                    # A fresh image retains neither EXIF nor ICC/XMP/descriptive metadata.
                    with Image.frombytes("RGB", image.size, pixels) as clean:
                        output = BytesIO()
                        clean.save(output, format="WEBP", quality=90)
                    encoded = output.getvalue()
                    if len(encoded) > MAX_BYTES:
                        raise ValidationError("The converted WebP exceeds the 8 MB storage limit.")
                    with Image.open(BytesIO(encoded)) as check:
                        check.load()
                        if check.format != "WEBP" or check.size != image.size:
                            raise ValidationError("The converted WebP failed validation.")
                    return ConvertedImage(
                        ContentFile(encoded, name="image.webp"), digest, original_size, image.size
                    )
                finally:
                    image.close()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise ValidationError("The file is not a valid supported image.") from exc
