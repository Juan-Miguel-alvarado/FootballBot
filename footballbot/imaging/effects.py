"""Efectos para la trivia: pixelar, desenfocar, silueta y zoom. Funciones puras: imagen entra,
imagen sale.

Nada aquí descarga ni guarda archivos. Pillow es lento para el bot (bloquea), así que
cogs/trivia.py llama `render_stage` con `asyncio.to_thread(...)`.

Cómo se arma cada imagen (`render_stage`):
1. `scaled_crest`: el escudo (o bandera) con su transparencia, al tamaño final.
2. El efecto de EFFECTS recibe ese escudo y devuelve la imagen terminada. La mayoría primero
   lo pega sobre el fondo gris (`on_background`) y después aplica el efecto a todo; la silueta
   necesita la transparencia, por eso trabaja sobre el escudo antes de pegarlo.

Para añadir un efecto: escribe una función `(escudo RGBA, nivel, semilla) -> imagen RGB`
y añádela a EFFECTS. Después úsala en un modo de services/trivia/modes.py.
"""

import io
import random
from collections.abc import Callable

from PIL import Image, ImageFilter

from footballbot.imaging.draw import outline_icon

SIZE = 400  # la imagen final es cuadrada, SIZE x SIZE píxeles
# Fondo oscuro (casi el negro del logo). Los escudos llevan un borde claro de sticker, así se
# ven también los negros (Juventus) sin poner un recuadro claro que encandile.
BACKGROUND = (18, 23, 32)
CREST_SCALE = 0.8  # el escudo ocupa el 80 % del lado; el resto es margen
# La silueta se rellena con el azul del logo: se ve sobre el fondo oscuro y es de la marca
SILHOUETTE_COLOR = (11, 150, 254)


def scaled_crest(data: bytes, outlined: bool = True) -> Image.Image:
    """Abre la imagen y la escala para que su lado mayor ocupe el 80 % de la imagen final.

    Con `outlined`, le añade el borde claro de sticker (el mismo de las tarjetas).
    """
    crest = Image.open(io.BytesIO(data)).convert("RGBA")
    target = SIZE * CREST_SCALE
    scale = target / max(crest.size)
    width, height = round(crest.width * scale), round(crest.height * scale)
    crest = crest.resize((width, height), Image.Resampling.LANCZOS)
    if not outlined:
        return crest
    stroke = 9
    padded = Image.new("RGBA", (width + 2 * stroke, height + 2 * stroke), (0, 0, 0, 0))
    padded.paste(crest, (stroke, stroke), crest)
    return outline_icon(padded, stroke)


def _box(crest: Image.Image) -> tuple[int, int, int, int]:
    """Dónde queda el escudo dentro de la imagen final (on_background lo centra)."""
    left, top = (SIZE - crest.width) // 2, (SIZE - crest.height) // 2
    return (left, top, left + crest.width, top + crest.height)


def on_background(crest: Image.Image) -> Image.Image:
    """Pega el escudo centrado sobre el fondo oscuro, al tamaño final."""
    canvas = Image.new("RGBA", (SIZE, SIZE), (*BACKGROUND, 255))
    # El tercer argumento usa la transparencia del escudo como máscara
    canvas.paste(crest, ((SIZE - crest.width) // 2, (SIZE - crest.height) // 2), crest)
    return canvas.convert("RGB")


def prepare(data: bytes) -> Image.Image:
    """El escudo sobre el fondo gris, sin efecto."""
    return on_background(scaled_crest(data))


def pixelate(image: Image.Image, blocks: float) -> Image.Image:
    """`blocks` = cuántos cuadros de ancho. 6 es casi irreconocible, 28 ya se ve bastante."""
    small_size = max(1, round(blocks))
    # Reducir promediando colores (BOX) y volver a agrandar sin suavizar (NEAREST) = cuadritos
    small = image.resize((small_size, small_size), Image.Resampling.BOX)
    return small.resize(image.size, Image.Resampling.NEAREST)


def blur(image: Image.Image, radius: float) -> Image.Image:
    """`radius` = cuánto se desenfoca. 32 es una mancha, 6 ya se reconoce."""
    return image.filter(ImageFilter.GaussianBlur(radius))


def silhouette(crest: Image.Image, color_amount: float) -> Image.Image:
    """El escudo relleno de negro (solo se ve la forma). `color_amount` 0-1 deja asomar el color.

    Necesita el escudo con transparencia: la forma sale del canal alfa. Los PNG de
    football-data tienen el fondo transparente.
    """
    # Los escudos vienen pequeños y se agrandan: el borde queda en escalones. Se suaviza la
    # transparencia y se vuelve a endurecer, así el contorno queda liso (sin dientes)
    alpha = crest.getchannel("A").filter(ImageFilter.GaussianBlur(1.1))
    alpha = alpha.point(lambda a: max(0, min(255, (a - 128) * 4 + 128)))
    shape = Image.new("RGBA", crest.size, (*SILHOUETTE_COLOR, 255))
    if color_amount > 0:
        shape = Image.blend(shape, crest, color_amount)
    shape.putalpha(alpha)
    return shape


def zoom(
    image: Image.Image,
    visible: float,
    seed: int,
    area: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """Muestra solo un trozo (`visible` = qué fracción del lado se ve: 0.2 es un trocito).

    El centro del trozo sale de `seed`: es el mismo en todas las etapas de una ronda, así el
    zoom se va abriendo sobre el mismo punto. `area` es dónde está el escudo: el trozo se
    queda dentro (si cabe), para no mostrar un pedazo del fondo como si fuera un mal recorte.
    """
    rng = random.Random(seed)
    side = max(8, visible * image.width)
    x0, y0, x1, y1 = area or (0, 0, image.width, image.height)

    def inside(low: int, high: int, fraction: float) -> float:
        # Un punto entre el 32 % y el 68 % del escudo, sin que el trozo se salga de él
        lo = max(low + (high - low) * 0.32, low + side / 2)
        hi = min(low + (high - low) * 0.68, high - side / 2)
        return lo + (hi - lo) * fraction if lo <= hi else (low + high) / 2

    cx = inside(x0, x1, rng.random())
    cy = inside(y0, y1, rng.random())
    left = min(max(0, cx - side / 2), image.width - side)
    top = min(max(0, cy - side / 2), image.height - side)
    box = (round(left), round(top), round(left + side), round(top + side))
    zoomed = image.crop(box).resize(image.size, Image.Resampling.LANCZOS)
    # Al agrandar tanto el escudo se ve blando: un poco de nitidez
    return zoomed.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))


# Cada efecto: (escudo RGBA ya escalado, nivel de la etapa, semilla de la ronda) -> imagen RGB
EFFECTS: dict[str, Callable[[Image.Image, float, int], Image.Image]] = {
    "none": lambda crest, level, seed: on_background(crest),
    "pixelate": lambda crest, level, seed: pixelate(on_background(crest), level),
    "blur": lambda crest, level, seed: blur(on_background(crest), level),
    "silhouette": lambda crest, level, seed: on_background(silhouette(crest, level)),  # sin borde
    "zoom": lambda crest, level, seed: zoom(on_background(crest), level, seed, _box(crest)),
}


def render_stage(data: bytes, effect: str, level: float | None, seed: int = 0) -> bytes:
    """Imagen de una etapa de la trivia, como PNG. `level=None` = la imagen sin efecto (revelar).

    `seed` fija lo que tiene que ser igual en toda la ronda (el punto del zoom).
    """
    # La silueta y el zoom van sin el borde de sticker: en la silueta se vería la forma del
    # borde, no la del escudo, y en el zoom el borde blanco parece un recorte mal hecho
    plain = effect in ("silhouette", "zoom") and level is not None
    crest = scaled_crest(data, outlined=not plain)
    image = on_background(crest) if level is None else EFFECTS[effect](crest, level, seed)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
