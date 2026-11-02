"""Herramientas de dibujo para las tarjetas (cards.py): fuentes, colores, degradados, texto.

Funciones puras con Pillow: no descargan nada. Todo el "estilo" (colores, fuentes) está aquí
arriba, en un solo lugar: si quieres cambiar el look de todas las tarjetas, empieza por aquí.

Fuentes (carpeta fonts/, licencia OFL = libres de usar y redistribuir):
- Inter: el texto normal y los números.
- Oswald: los títulos (alta y condensada, estilo deportivo).
Las dos son "variables": un solo archivo trae todos los pesos (Regular, SemiBold, Bold...).
"""

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILES = {"text": "Inter.ttf", "title": "Oswald.ttf"}

RGB = tuple[int, int, int]

# --- paleta (tema oscuro) ----------------------------------------------------------------------
BG_TOP: RGB = (24, 28, 38)
BG_BOTTOM: RGB = (12, 14, 20)
ROW_A: RGB = (30, 35, 47)
ROW_B: RGB = (25, 29, 40)
TEXT: RGB = (240, 242, 247)
MUTED: RGB = (150, 158, 175)
WIN: RGB = (52, 199, 89)
DRAW: RGB = (255, 204, 0)
LOSS: RGB = (234, 67, 53)


@lru_cache(maxsize=64)
def font(kind: str, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    """Fuente `kind` ("text" o "title") en ese tamaño y peso. Se guarda en caché."""
    loaded = ImageFont.truetype(str(FONTS_DIR / FONT_FILES[kind]), size)
    loaded.set_variation_by_name(weight)
    return loaded


def hex_rgb(value: int) -> RGB:
    """0x3D195B -> (61, 25, 91)."""
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


def mix(a: RGB, b: RGB, amount: float) -> RGB:
    """Mezcla dos colores: amount=0 da `a`, amount=1 da `b`."""
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


def readable_on(color: RGB) -> RGB:
    """Texto blanco o casi negro según qué se lee mejor sobre `color`."""
    luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    return (20, 22, 28) if luminance > 160 else TEXT


def vertical_gradient(size: tuple[int, int], top: RGB, bottom: RGB) -> Image.Image:
    """Fondo con degradado de arriba hacia abajo."""
    height = size[1]
    column = Image.new("RGB", (1, height))
    for y in range(height):
        column.putpixel((0, y), mix(top, bottom, y / max(1, height - 1)))
    return column.resize(size)


def accent_band(size: tuple[int, int], accent: RGB) -> Image.Image:
    """Banda de cabecera: el color de acento a la izquierda que se funde con el fondo."""
    width = size[0]
    row = Image.new("RGB", (width, 1))
    for x in range(width):
        row.putpixel((x, 0), mix(mix(accent, BG_TOP, 0.25), BG_TOP, min(1.0, x / (width * 0.9))))
    return row.resize(size)


def fade_mask(size: tuple[int, int], start: float = 0.5) -> Image.Image:
    """Máscara de transparencia: opaca arriba y se desvanece desde `start` (0-1) hasta abajo."""
    height = size[1]
    column = Image.new("L", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel((0, y), 255 if t < start else round(255 * (1 - (t - start) / (1 - start))))
    return column.resize(size)


def fit_font(
    text: str, kind: str, weight: str, max_size: int, max_width: int, min_size: int = 12
) -> ImageFont.FreeTypeFont:
    """La fuente más grande (hasta `max_size`) con la que `text` cabe en `max_width` píxeles."""
    size = max_size
    while size > min_size and font(kind, size, weight).getlength(text) > max_width:
        size -= 2
    return font(kind, size, weight)


def truncate(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Corta el texto con "…" si no cabe en `max_width`."""
    if fnt.getlength(text) <= max_width:
        return text
    while text and fnt.getlength(text + "…") > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def load_icon(data: bytes | None, size: int) -> Image.Image | None:
    """Escudo/logo cuadrado de `size` px con su transparencia, o None si no hay imagen."""
    if not data:
        return None
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
    except OSError:  # no es una imagen válida
        return None
    scale = size / max(image.size)
    image = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2), image)
    return canvas


def paste_icon(
    canvas: Image.Image, icon: Image.Image | None, center: tuple[int, int], shadow: bool = False
) -> None:
    """Pega un icono centrado en `center`. Con `shadow`, le pone una sombra suave debajo."""
    if icon is None:
        return
    x = center[0] - icon.width // 2
    y = center[1] - icon.height // 2
    if shadow:
        alpha = icon.getchannel("A").filter(ImageFilter.GaussianBlur(icon.width // 14 or 1))
        dark = Image.new("RGBA", icon.size, (0, 0, 0, 0))
        dark.putalpha(alpha.point(lambda a: a * 0.6))
        canvas.paste(dark, (x + icon.width // 30, y + icon.width // 20), dark)
    canvas.paste(icon, (x, y), icon)


def pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: RGB,
    text: str = "",
    fnt: ImageFont.FreeTypeFont | None = None,
) -> None:
    """Rectángulo con puntas redondas ("chip"), con texto centrado opcional."""
    radius = (box[3] - box[1]) // 2
    draw.rounded_rectangle(box, radius=radius, fill=fill)
    if text and fnt:
        center = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        draw.text(center, text, font=fnt, fill=readable_on(fill), anchor="mm")


def to_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


# Colores con los que la API describe a los clubes ("White / Purple", "Red / Navy Blue")
COLOR_NAMES: dict[str, RGB] = {
    "red": (210, 35, 42), "claret": (122, 38, 58), "maroon": (128, 0, 32),
    "burgundy": (128, 0, 32), "blue": (30, 90, 200), "navy": (20, 40, 100),
    "navy blue": (20, 40, 100), "royal blue": (30, 70, 190), "sky blue": (108, 171, 221),
    "dark blue": (0, 45, 120), "blue-white": (30, 90, 200),
    "dark red": (140, 20, 30), "light green": (90, 190, 90), "pink": (230, 120, 170),
    "cyan": (0, 170, 200), "turquoise": (0, 170, 170), "lime": (150, 210, 40),
    "light blue": (108, 171, 221), "green": (0, 140, 70), "dark green": (0, 90, 50),
    "yellow": (250, 210, 0), "gold": (212, 175, 55), "orange": (245, 130, 32),
    "purple": (110, 50, 160), "violet": (110, 50, 160), "black": (40, 40, 40),
    "grey": (130, 130, 130), "gray": (130, 130, 130), "silver": (170, 170, 170),
    "white": (235, 235, 235), "amber": (255, 191, 0), "brown": (120, 72, 40),
}  # fmt: skip
NEUTRAL = {"white", "black", "grey", "gray", "silver"}
NEUTRAL_ACCENT: RGB = (85, 90, 105)


def color_from_names(colors: str | None, default: RGB = WIN) -> RGB:
    """El color del club a partir de "White / Purple": el primero que no sea blanco/negro/gris."""
    if not colors:
        return default
    names = [c.strip().lower() for c in colors.replace("-", "/").split("/")]
    known = [n for n in names if n in COLOR_NAMES]
    for name in known:
        if name not in NEUTRAL:
            return COLOR_NAMES[name]
    # Solo blanco/negro/gris (Juventus, Newcastle...): un gris oscuro, para que el texto se lea
    return NEUTRAL_ACCENT if known else default


# Medallas del podio y del ranking
GOLD: RGB = (255, 196, 0)
SILVER: RGB = (192, 198, 210)
BRONZE: RGB = (205, 127, 50)
MEDALS: tuple[RGB, ...] = (GOLD, SILVER, BRONZE)


def avatar(
    data: bytes | None, size: int, name: str = "?", fill: RGB = (88, 101, 242)
) -> Image.Image:
    """Avatar redondo de `size` px. Sin imagen, un círculo de color con la inicial del nombre."""
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)  # borde suave

    picture: Image.Image | None = None
    if data:
        try:
            picture = (
                Image.open(io.BytesIO(data))
                .convert("RGBA")
                .resize((size, size), Image.Resampling.LANCZOS)
            )
        except OSError:
            picture = None
    if picture is None:
        picture = Image.new("RGBA", (size, size), (*fill, 255))
        initial = (name.strip()[:1] or "?").upper()
        ImageDraw.Draw(picture).text(
            (size // 2, size // 2), initial, font=font("title", size // 2, "Bold"),
            fill=TEXT, anchor="mm",
        )  # fmt: skip
    picture.putalpha(mask)
    return picture
