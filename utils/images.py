"""Tratamento de imagem: recorte e faixa de identificacao.

Usa Pillow. Nao distorce nem reduz a imagem original alem do recorte
explicito pedido no config.yaml.
"""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

BANNER_HEIGHT_RATIO = 0.055
BANNER_MIN_HEIGHT = 48
BANNER_BG = (17, 24, 39)
BANNER_FG = (255, 255, 255)
ACCENT = (56, 189, 248)

SYSTEM_LABEL = {"grafana": "Grafana", "flowbix": "Flowbix"}


def load_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def crop_image(data: bytes, region: dict[str, int] | None) -> bytes:
    """Recorta a regiao configurada, respeitando os limites da imagem."""
    if not region:
        return data
    image = load_image(data)
    x = max(0, int(region.get("x", 0)))
    y = max(0, int(region.get("y", 0)))
    width = int(region.get("width", image.width))
    height = int(region.get("height", image.height))

    right = min(image.width, x + width)
    bottom = min(image.height, y + height)
    if right <= x or bottom <= y:
        raise ValueError(f"Regiao de recorte invalida para uma imagem {image.width}x{image.height}: {region}")

    return to_png_bytes(image.crop((x, y, right, bottom)))


def _font(size: int) -> ImageFont.ImageFont:
    """Tenta fontes comuns no Linux; cai no default do Pillow se nao houver."""
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()
