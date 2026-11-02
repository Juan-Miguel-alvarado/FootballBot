"""Herramientas de dibujo para las tarjetas: fuentes, colores, logo, texto.

Funciones puras con Pillow: no descargan nada. Todo el "estilo" (colores, fuentes, logo) está
aquí arriba, en un solo lugar: si quieres cambiar el look de todas las tarjetas, empieza aquí.

Estilo "Fragmentos azules" (el del logo del bot, assets/logo.png): fondo negro plano, un solo
azul eléctrico, esquinas rectas, el logo como marca y sus fragmentos como decoración.
Sin degradados de fondo, sin sombras y sin píldoras redondeadas.

Fuentes (carpeta fonts/, licencia OFL = libres de usar y redistribuir):
- Inter: el texto normal y los números.
- Oswald: los títulos (alta y condensada, estilo deportivo).
Las dos son "variables": un solo archivo trae todos los pesos (Regular, SemiBold, Bold...).
"""

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FILES = {"text": "Inter.ttf", "title": "Oswald.ttf"}
LOGO_FILE = Path(__file__).resolve().parent / "assets" / "logo.png"

RGB = tuple[int, int, int]

# --- paleta (sacada del logo del bot) ----------------------------------------------------------
BLACK: RGB = (0, 0, 0)  # el fondo del logo: así el logo se pega sin recuadro
PANEL: RGB = (11, 14, 20)  # filas y paneles, apenas más claros que el fondo
LINE: RGB = (28, 36, 50)  # líneas finas y bordes apagados
BLUE: RGB = (11, 150, 254)  # el azul claro del balón (#0B96FE)
BLUE_DEEP: RGB = (3, 98, 255)  # el azul profundo del balón (#0362FF)
TEXT: RGB = (242, 245, 250)
MUTED: RGB = (125, 136, 153)
WIN: RGB = BLUE
DRAW: RGB = (90, 99, 116)
LOSS: RGB = (214, 69, 69)  # rojo apagado: solo para perder y descender


@lru_cache(maxsize=64)
def font(kind: str, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    """Fuente `kind` ("text" o "title") en ese tamaño y peso. Se guarda en caché."""
    loaded = ImageFont.truetype(str(FONTS_DIR / FONT_FILES[kind]), size)
    loaded.set_variation_by_name(weight)
    return loaded


def hex_rgb(value: int) -> RGB:
    """0x3D195B -> (61, 25, 91)."""
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


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


def to_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


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


# --- el logo del bot ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _logo_rgba() -> Image.Image:
    """El logo con el negro convertido en transparencia (para pegarlo sobre cualquier fondo).

    El logo es azul sobre negro: lo oscuro pasa a transparente y lo azul queda opaco, con los
    bordes suaves.
    """
    source = Image.open(LOGO_FILE).convert("RGB")
    alpha = source.convert("L").point(lambda v: min(255, v * 3))
    logo = source.convert("RGBA")
    logo.putalpha(alpha)
    return logo.crop(logo.getbbox())


def logo(size: int, opacity: float = 1.0) -> Image.Image:
    """El logo (balón + fragmentos) de `size` px de ancho, con fondo transparente."""
    image = _logo_rgba()
    height = round(image.height * size / image.width)
    image = image.resize((size, height), Image.Resampling.LANCZOS)
    if opacity < 1:
        image.putalpha(image.getchannel("A").point(lambda a: round(a * opacity)))
    return image


def shards(width: int, opacity: float = 1.0) -> Image.Image:
    """Solo los fragmentos que salen volando del balón, recortados del logo."""
    image = _logo_rgba()
    # Los fragmentos están en la parte derecha del logo
    crop = image.crop((round(image.width * 0.6), 0, image.width, image.height))
    crop = crop.crop(crop.getbbox())
    height = round(crop.height * width / crop.width)
    crop = crop.resize((width, height), Image.Resampling.LANCZOS)
    if opacity < 1:
        crop.putalpha(crop.getchannel("A").point(lambda a: round(a * opacity)))
    return crop


def paste(canvas: Image.Image, image: Image.Image, xy: tuple[int, int]) -> None:
    """Pega una imagen con transparencia (se puede salir del borde: se recorta sola)."""
    canvas.alpha_composite(image, dest=(max(0, xy[0]), max(0, xy[1])),
                           source=(max(0, -xy[0]), max(0, -xy[1])))  # fmt: skip


def hex_texture(canvas: Image.Image, box: tuple[int, int, int, int], size: int = 34) -> None:
    """Hexágonos del balón, muy tenues, dentro de `box` (textura de fondo)."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w = math.sqrt(3) * size
    row = 0
    y = box[1]
    while y < box[3] + size:
        x = box[0] + (w / 2 if row % 2 else 0)
        while x < box[2] + w:
            points = [
                (x + size * math.cos(math.radians(60 * i + 30)),
                 y + size * math.sin(math.radians(60 * i + 30)))
                for i in range(6)
            ]  # fmt: skip
            draw.polygon(points, outline=(*BLUE, 26))
            x += w
        y += size * 1.5
        row += 1
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    layer.putalpha(Image.composite(layer.getchannel("A"), mask, mask))
    canvas.alpha_composite(layer)


def brand(canvas: Image.Image, right: int, top: int, size: int = 64) -> None:
    """El logo pequeño, como marca de canal de TV, con su borde derecho en `right`."""
    mark = logo(size)
    paste(canvas, mark, (right - mark.width, top))


def tile(
    canvas: Image.Image,
    data: bytes | None,
    box: tuple[int, int, int, int],
    border: RGB | None = None,
    fill: RGB = (236, 239, 244),
) -> None:
    """Escudo o logo sobre un cuadro claro de esquinas rectas (se ven también los oscuros)."""
    draw = ImageDraw.Draw(canvas)
    if border:
        draw.rectangle((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3), fill=border)
    draw.rectangle(box, fill=fill)
    side = min(box[2] - box[0], box[3] - box[1])
    icon = load_icon(data, round(side * 0.82))
    paste_icon(canvas, icon, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))


def wordmark(draw: ImageDraw.ImageDraw, xy: tuple[int, int], anchor: str = "ls") -> None:
    """ "FOOTBALLTRIVIA" en pequeño, con FOOTBALL en blanco y TRIVIA en azul."""
    fnt = font("title", 18, "SemiBold")
    x, y = xy
    first, second = "FOOTBALL", "TRIVIA"
    width = fnt.getlength(first + second)
    if anchor.startswith("r"):
        x -= width
    draw.text((x, y), first, font=fnt, fill=TEXT, anchor="l" + anchor[1])
    draw.text((x + fnt.getlength(first), y), second, font=fnt, fill=BLUE, anchor="l" + anchor[1])
