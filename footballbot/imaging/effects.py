"""Efectos para la trivia: pixelar y desenfocar escudos. Funciones puras: imagen entra, imagen sale.

Nada aquí descarga ni guarda archivos. Pillow es lento para el bot (bloquea), así que
cogs/trivia.py llama `render_stage` con `asyncio.to_thread(...)`.

Para añadir un efecto (ej. silhouette): escribe la función y añádela a EFFECTS.
"""

import io
from collections.abc import Callable

from PIL import Image, ImageFilter

SIZE = 400  # la imagen final es cuadrada, SIZE x SIZE píxeles
# Gris claro de fondo: un escudo negro o blanco con transparencia se ve en tema claro y oscuro
BACKGROUND = (226, 229, 233)
CREST_SCALE = 0.8  # el escudo ocupa el 80 % del lado; el resto es margen


def prepare(data: bytes) -> Image.Image:
    """Abre la imagen y la centra sobre el fondo gris, al tamaño final."""
    crest = Image.open(io.BytesIO(data)).convert("RGBA")
    target = SIZE * CREST_SCALE
    scale = target / max(crest.size)
    width, height = round(crest.width * scale), round(crest.height * scale)
    crest = crest.resize((width, height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (SIZE, SIZE), (*BACKGROUND, 255))
    # El tercer argumento usa la transparencia del escudo como máscara
    canvas.paste(crest, ((SIZE - width) // 2, (SIZE - height) // 2), crest)
    return canvas.convert("RGB")


def pixelate(image: Image.Image, blocks: float) -> Image.Image:
    """`blocks` = cuántos cuadros de ancho. 6 es casi irreconocible, 28 ya se ve bastante."""
    small_size = max(1, round(blocks))
    # Reducir promediando colores (BOX) y volver a agrandar sin suavizar (NEAREST) = cuadritos
    small = image.resize((small_size, small_size), Image.Resampling.BOX)
    return small.resize(image.size, Image.Resampling.NEAREST)


def blur(image: Image.Image, radius: float) -> Image.Image:
    """`radius` = cuánto se desenfoca. 32 es una mancha, 6 ya se reconoce."""
    return image.filter(ImageFilter.GaussianBlur(radius))


EFFECTS: dict[str, Callable[[Image.Image, float], Image.Image]] = {
    "pixelate": pixelate,
    "blur": blur,
}


def render_stage(data: bytes, effect: str, level: float | None) -> bytes:
    """Imagen de una etapa de la trivia, como PNG. `level=None` = la imagen sin efecto (revelar)."""
    image = prepare(data)
    if level is not None:
        image = EFFECTS[effect](image, level)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
