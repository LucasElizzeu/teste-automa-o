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


def annotate_image(
    data: bytes,
    site: str,
    system: str,
    moment: datetime,
    description: str = "",
    period: str | None = None,
) -> bytes:
    """Adiciona uma faixa de identificacao no topo da imagem.

    Motivo: quando o print circula no celular/grupo, o contexto do circuito
    precisa estar dentro da propria imagem, nao so na legenda.
    """
    image = load_image(data)
    banner_h = max(BANNER_MIN_HEIGHT, int(image.height * BANNER_HEIGHT_RATIO))

    canvas = Image.new("RGB", (image.width, image.height + banner_h), BANNER_BG)
    canvas.paste(image, (0, banner_h))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([(0, 0), (image.width, banner_h)], fill=BANNER_BG)
    draw.rectangle([(0, banner_h - 2), (image.width, banner_h)], fill=ACCENT)

    label = SYSTEM_LABEL.get(system.lower(), system.capitalize())
    arrow = site.replace(" - ", " → ").replace(" -> ", " → ")

    font_main = _font(max(14, int(banner_h * 0.42)))
    font_sub = _font(max(11, int(banner_h * 0.30)))

    padding = max(10, int(banner_h * 0.22))
    draw.text((padding, int(banner_h * 0.16)), arrow, font=font_main, fill=BANNER_FG)

    right_text = f"{label} | {moment.strftime('%d/%m/%Y %H:%M')}"
    if period:
        right_text += f" | {period}"
    try:
        bbox = draw.textbbox((0, 0), right_text, font=font_sub)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = len(right_text) * 7
    draw.text(
        (max(padding, image.width - text_w - padding), int(banner_h * 0.58)),
        right_text,
        font=font_sub,
        fill=(200, 215, 230),
    )

    if description:
        try:
            bbox = draw.textbbox((0, 0), description, font=font_sub)
            desc_w = bbox[2] - bbox[0]
        except Exception:
            desc_w = len(description) * 7
        draw.text(
            (max(padding, int((image.width - desc_w) / 2)), int(banner_h * 0.16)),
            description,
            font=font_sub,
            fill=(170, 190, 210),
        )

    return to_png_bytes(canvas)
