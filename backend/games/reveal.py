"""Private image compositor. Never serve an original image behind a client-side cover."""

from io import BytesIO

from django.core.cache import cache
from django.core.files.storage import default_storage
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from .services import GameError, revealed_count

IMAGE_SIZE = (960, 720)
COVER_COLOR = (35, 33, 48)


def prepare_image(storage_name):
    key = f"game-source:v1:{storage_name}"
    encoded = cache.get(key)
    if encoded is not None:
        return Image.open(BytesIO(encoded)).convert("RGB")
    try:
        with default_storage.open(storage_name, "rb") as file, Image.open(file) as original:
            original.load()
            image = Image.new("RGB", IMAGE_SIZE, (20, 21, 31))
            fitted = ImageOps.contain(ImageOps.exif_transpose(original).convert("RGB"), IMAGE_SIZE)
            image.paste(
                fitted, ((IMAGE_SIZE[0] - fitted.width) // 2, (IMAGE_SIZE[1] - fitted.height) // 2)
            )
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise GameError(
            "This image is temporarily unavailable. Please try another picture.",
            "image_unavailable",
            503,
        ) from exc
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    cache.set(key, buffer.getvalue(), timeout=300)
    return image


def render_reveal(game_round, now):
    count = revealed_count(game_round, now)
    image = (
        prepare_image(game_round.image_storage_name)
        if count
        else Image.new("RGB", IMAGE_SIZE, COVER_COLOR)
    )
    visible = set(game_round.reveal_order[:count])
    draw = ImageDraw.Draw(image)
    grid = game_round.grid_size
    for tile in range(grid * grid):
        if tile in visible:
            continue
        row, column = divmod(tile, grid)
        x0, y0 = column * image.width // grid, row * image.height // grid
        x1, y1 = (column + 1) * image.width // grid, (row + 1) * image.height // grid
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=COVER_COLOR)
    buffer = BytesIO()
    image.save(buffer, format="WEBP", lossless=True, method=1)
    return buffer.getvalue(), count
