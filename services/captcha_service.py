"""
Локальная CAPTCHA для регистрации (Pillow, без внешних API).
"""

from __future__ import annotations

import io
import random
import string
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

CAPTCHA_LENGTH = 5
CAPTCHA_MAX_ATTEMPTS = 5
CAPTCHA_CHARS = string.ascii_uppercase + string.digits


def generate_captcha_code(length: int = CAPTCHA_LENGTH) -> str:
    return "".join(random.choice(CAPTCHA_CHARS) for _ in range(length))


def _load_font(size: int = 36):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def generate_captcha_image(code: str) -> bytes:
    """Сгенерировать PNG с шумом, линиями и наклонными символами."""
    width, height = 220, 80
    image = Image.new("RGB", (width, height), (random.randint(220, 245),) * 3)
    draw = ImageDraw.Draw(image)
    font = _load_font(34)

    for _ in range(8):
        draw.line(
            (
                random.randint(0, width),
                random.randint(0, height),
                random.randint(0, width),
                random.randint(0, height),
            ),
            fill=(
                random.randint(80, 180),
                random.randint(80, 180),
                random.randint(80, 180),
            ),
            width=random.randint(1, 2),
        )

    for _ in range(120):
        draw.point(
            (random.randint(0, width - 1), random.randint(0, height - 1)),
            fill=(random.randint(0, 200), random.randint(0, 200), random.randint(0, 200)),
        )

    slot_width = width // (len(code) + 1)
    for index, char in enumerate(code):
        char_img = Image.new("RGBA", (50, 60), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text(
            (8, 8),
            char,
            font=font,
            fill=(
                random.randint(10, 80),
                random.randint(10, 80),
                random.randint(10, 80),
            ),
        )
        angle = random.randint(-25, 25)
        rotated = char_img.rotate(angle, expand=1, resample=Image.Resampling.BICUBIC)
        x = slot_width * (index + 1) - rotated.width // 2 + random.randint(-6, 6)
        y = height // 2 - rotated.height // 2 + random.randint(-8, 8)
        image.paste(rotated, (x, y), rotated)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def verify_captcha(user_input: str, expected: str) -> bool:
    if not user_input or not expected:
        return False
    return user_input.strip().upper() == expected.strip().upper()


def new_captcha() -> Tuple[str, bytes]:
    code = generate_captcha_code()
    return code, generate_captcha_image(code)
