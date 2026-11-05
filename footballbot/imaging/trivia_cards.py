"""Tarjetas de la trivia: cada ronda, la respuesta, el podio final y el ranking (issue #11).

Igual que cards.py: reciben datos ya preparados (imágenes en bytes, nombres, puntos) y
devuelven un PNG. cogs/trivia.py las llama con `asyncio.to_thread`.

El efecto (pixelado, borroso...) se aplica SOLO al escudo, con imaging/effects.py, antes de
llegar aquí: `round_card` recibe esa imagen ya procesada y la enmarca, así el texto de la
tarjeta nunca se pixela.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw

from footballbot.imaging.draw import (
    BLACK,
    BLUE,
    LINE,
    LOSS,
    MUTED,
    PANEL,
    RGB,
    TEXT,
    avatar,
    avatar_fill,
    brand,
    fit_font,
    font,
    hex_texture,
    paste,
    shards,
    tile,
    to_png,
    truncate,
    wordmark,
)

WIDTH = 800
# Bloques del podio: de más brillante (1º) a más apagado (3º), todos del azul del logo
PODIUM_FILLS: tuple[RGB, RGB, RGB] = (BLUE, (12, 92, 168), (16, 50, 100))
# Texto secundario en filas oscuras: más claro que MUTED para que se lea en el celular
SOFT: RGB = (186, 194, 208)
# Aros de los avatares del podio: más claros que los bloques, para que se vean sobre el negro
RING_FILLS: tuple[RGB, RGB, RGB] = (BLUE, (40, 120, 220), (60, 100, 170))
# Texto de lo que ya pasó (puntos de etapas vencidas): casi del color del fondo
LINE_TEXT: RGB = (70, 80, 98)


@dataclass(frozen=True, slots=True)
class PlayerEntry:
    """Un jugador en el podio o en el ranking."""

    name: str
    avatar: bytes | None
    points: int
    detail: str = ""  # "4 correct · best streak 3"


# --- ronda -------------------------------------------------------------------------------------


def round_card(
    *,
    stage_image: bytes,
    round_no: int,
    total_rounds: int,
    title: str,
    stage: int,
    points: Sequence[int],
    prompt: str = "",
    seconds: int | None = None,
    cue: str | None = None,
) -> bytes:
    """Una ronda: "ROUND 3/10", la imagen en un marco, la pregunta y la barra de etapas.

    `seconds`: cada cuánto se aclara la imagen; se dice en la cabecera ("CLEARER IN 5 S", o
    "LAST CHANCE" en la última etapa). `cue` cambia "CLEARER" por lo que hace el modo
    ("WIDER" en el zoom, "COLOR" en la silueta).
    """
    height = 740
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    draw = ImageDraw.Draw(canvas)
    subtitle = title.upper()
    if seconds:
        change = cue or "CLEARER"
        subtitle += " · LAST CHANCE" if stage == len(points) - 1 else f" · {change} IN {seconds} S"
    _header(canvas, draw, f"Round {round_no}/{total_rounds}", subtitle, accent=True)

    # La imagen de la etapa (ya con fondo oscuro) en un marco recto fino
    size = 432
    left, top = (WIDTH - size) // 2, 150
    draw.rectangle((left - 2, top - 2, left + size + 1, top + size + 1), fill=LINE)
    image = Image.open(io.BytesIO(stage_image)).convert("RGBA").resize((size, size))
    canvas.paste(image, (left, top))

    # La pregunta, grande, debajo de la imagen
    if prompt:
        prompt_font = fit_font(prompt.upper(), "title", "SemiBold", 34, WIDTH - 80, 22)
        draw.text((WIDTH // 2, 624), prompt.upper(), font=prompt_font, fill=TEXT, anchor="mm")

    # Barra de etapas: la actual en azul con "NOW", las pasadas apagadas, las que vienen con
    # borde. Así se entiende que son los puntos que se ganan ahora, no opciones para elegir
    gap = 10
    segment = (WIDTH - 72 - gap * (len(points) - 1)) // len(points)
    y0, y1 = 662, 716
    for i, value in enumerate(points):
        x0 = 36 + i * (segment + gap)
        box = (x0, y0, x0 + segment, y1)
        label = f"{value} PTS"
        if i == stage:
            draw.rectangle(box, fill=BLUE)
            color = TEXT
            label += " NOW"
        elif i < stage:
            draw.rectangle(box, fill=PANEL)
            color = LINE_TEXT  # ya no se pueden ganar
        else:
            draw.rectangle(box, outline=LINE, width=2)
            color = MUTED
        draw.text((x0 + segment // 2, (y0 + y1) // 2), label,
                  font=font("title", 27, "SemiBold"), fill=color, anchor="mm")  # fmt: skip
    return to_png(canvas)


# --- respuesta ---------------------------------------------------------------------------------


def reveal_card(
    *,
    crest: bytes,
    name: str,
    subtitle: str | None,
    headline: str,
    success: bool,
    label: str | None = None,
    points: int | None = None,
) -> bytes:
    """La respuesta: escudo limpio, nombre, "País · Liga" y quién acertó (o que nadie).

    `label` es "Round 3/10"; `headline`, "Messi10 got it" o "Nobody got it"; `points`, lo que
    ganó (va grande y en azul). Tiene la misma cabecera que la ronda. Si alguien acertó, los
    fragmentos del logo salen volando del escudo; si no, caen apagados.
    """
    height = 700
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    cx = WIDTH // 2
    burst = shards(140, opacity=1.0 if success else 0.7)
    if not success:
        # Sin acierto: los fragmentos en gris y "cayendo" (girados hacia abajo)
        # Gris con un toque del rojo de "fallo", como la raya de abajo
        gray = Image.new("RGBA", burst.size, (150, 120, 128, 255))
        gray.putalpha(burst.getchannel("A"))
        burst = gray.rotate(-35, expand=True, resample=Image.Resampling.BICUBIC)
    # A los dos lados del escudo, como si el balón estallara
    paste(canvas, burst, (cx + 136, 196))
    mirrored = burst.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    paste(canvas, mirrored, (cx - 136 - mirrored.width, 196))
    draw = ImageDraw.Draw(canvas)
    _header(canvas, draw, label or "Answer", "ANSWER" if label else "", accent=success)

    tile(canvas, crest, (cx - 120, 158, cx + 120, 398))

    name_font = fit_font(name.upper(), "title", "Bold", 62, WIDTH - 80, 28)
    draw.text((cx, 460), name.upper(), font=name_font, fill=TEXT, anchor="mm")
    if subtitle:
        draw.text((cx, 512), subtitle, font=font("text", 30, "Medium"), fill=SOFT, anchor="mm")

    # Quién acertó, como texto (no como botón): el nombre en blanco y los puntos grandes en azul
    result_font = font("title", 38, "SemiBold")
    points_font = font("title", 64, "Bold")
    text = truncate(headline.upper(), result_font, WIDTH - 300)
    extra = f"+{points}" if success and points else ""
    gap = 18 if extra else 0
    width = result_font.getlength(text) + gap + (points_font.getlength(extra) if extra else 0)
    x = cx - width / 2
    draw.text((x, 590), text, font=result_font, fill=TEXT, anchor="lm")
    if extra:
        draw.text((x + result_font.getlength(text) + gap, 588), extra, font=points_font,
                  fill=BLUE, anchor="lm")  # fmt: skip
    # Una raya debajo: azul si alguien acertó, roja apagada si no
    draw.rectangle((cx - 60, 634, cx + 60, 637), fill=BLUE if success else LOSS)
    wordmark(draw, (36, height - 24), anchor="lm")
    return to_png(canvas)


# --- podio y ranking ---------------------------------------------------------------------------


def podium_card(*, title: str, subtitle: str, players: Sequence[PlayerEntry]) -> bytes:
    """Final de la partida: podio con avatares para los 3 primeros y la lista del resto."""
    rest = list(players[3:10])
    row_h = 56
    height = 660 + (len(rest) * row_h + 30 if rest else 0)
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    draw = ImageDraw.Draw(canvas)
    _header(canvas, draw, title, subtitle)

    # Orden visual del podio: 2º a la izquierda, 1º al centro, 3º a la derecha. Los tres
    # bloques se dibujan siempre (así queda centrado); un puesto sin jugador queda apagado.
    floor = 580
    # Con 2 jugadores, solo dos escalones centrados; con 1, uno solo en el centro
    spots = {
        1: ((0, 400, 240),),
        2: ((1, 305, 180), (0, 495, 250)),
    }.get(len(players), ((1, 210, 180), (0, 400, 250), (2, 590, 140)))
    for place, x, block_h in spots:
        top = floor - block_h
        player = players[place]
        draw.rectangle((x - 92, top, x + 92, floor), fill=PODIUM_FILLS[place])
        draw.text((x, top + 44), str(place + 1), font=font("title", 60, "Bold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
        draw.text((x, top + 104), f"{player.points} PTS",
                  font=font("title", 42 if place == 0 else 30, "SemiBold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
        size = 104 if place == 0 else 88
        ay = top - 34 - size // 2 - 30
        ring = size // 2 + 4
        draw.ellipse((x - ring, ay - ring, x + ring, ay + ring), fill=RING_FILLS[place])
        picture = avatar(player.avatar, size, player.name, fill=avatar_fill(player.name))
        canvas.paste(picture, (x - size // 2, ay - size // 2), picture)
        if place == 0:
            # El ganador "rompe" el balón: los fragmentos del logo saliendo de su avatar
            burst = shards(84)
            paste(canvas, burst, (x + ring + 6, ay - burst.height // 2))
            mirrored = burst.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            paste(canvas, mirrored, (x - ring - 6 - burst.width, ay - burst.height // 2))
        name_font = font("text", 25, "SemiBold")
        draw.text((x, ay + ring + 22), truncate(player.name, name_font, 190), font=name_font,
                  fill=TEXT, anchor="mm")  # fmt: skip

    if rest:
        y = floor + 30
        for i, player in enumerate(rest, start=4):
            _player_row(canvas, draw, y, row_h, i, player, small=True)
            y += row_h
    wordmark(draw, (36, height - 26), anchor="lm")
    return to_png(canvas)


def leaderboard_card(*, title: str, subtitle: str, players: Sequence[PlayerEntry]) -> bytes:
    """El ranking del servidor: puesto, avatar, nombre, aciertos y puntos de cada jugador."""
    row_h = 76
    height = 150 + len(players) * row_h + 70
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    draw = ImageDraw.Draw(canvas)
    _header(canvas, draw, title, subtitle)
    y = 150
    for i, player in enumerate(players, start=1):
        _player_row(canvas, draw, y, row_h, i, player)
        y += row_h
    wordmark(draw, (36, height - 28), anchor="lm")
    return to_png(canvas)


def _header(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    accent: bool | None = None,
) -> None:
    """La misma cabecera en todas las tarjetas de la trivia: título, subtítulo, el logo del
    bot y la línea azul.

    `accent`: None = subtítulo en texto normal (podio, ranking); True = en mayúsculas azules
    (ronda, respuesta acertada); False = en mayúsculas grises (nadie acertó).
    """
    hex_texture(canvas, (0, 0, WIDTH, 126))
    draw.text((36, 50), title.upper(), font=font("title", 48, "Bold"), fill=TEXT, anchor="lm")
    if accent is None:
        draw.text((38, 98), subtitle, font=font("text", 23, "Medium"), fill=SOFT, anchor="lm")
    else:
        draw.text((38, 98), subtitle, font=font("title", 25, "SemiBold"),
                  fill=BLUE if accent else SOFT, anchor="lm")  # fmt: skip
    brand(canvas, right=WIDTH - 28, top=22, size=118)
    draw.rectangle((0, 124, WIDTH, 127), fill=BLUE)


def _player_row(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    y: int,
    row_h: int,
    rank: int,
    player: PlayerEntry,
    small: bool = False,
) -> None:
    middle = y + row_h // 2
    if rank % 2:
        draw.rectangle((24, y, WIDTH - 24, y + row_h - 1), fill=PANEL)
    # Puesto: cuadrado azul para los 3 primeros, número gris para el resto
    if rank <= 3:
        draw.rectangle((44, middle - 19, 82, middle + 19), fill=PODIUM_FILLS[rank - 1])
        draw.text((63, middle), str(rank), font=font("title", 24, "Bold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
    else:
        draw.text((63, middle), str(rank), font=font("title", 26, "SemiBold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
    size = row_h - (22 if small else 20)
    picture = avatar(player.avatar, size, player.name, fill=avatar_fill(player.name))
    canvas.paste(picture, (104, middle - size // 2), picture)
    name_font = font("text", 26 if small else 28, "SemiBold")
    text_x = 104 + size + 18
    if player.detail and not small:
        draw.text((text_x, middle - 15), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
        detail_font = font("text", 23, "Medium")
        draw.text((text_x, middle + 18), truncate(player.detail, detail_font, 430),
                  font=detail_font, fill=SOFT, anchor="lm")  # fmt: skip
    else:
        draw.text((text_x, middle), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
    if rank == 1 and not small:
        # El primero: una franja azul a la izquierda y sus puntos más grandes
        draw.rectangle((24, y, 30, y + row_h - 1), fill=BLUE)
    size_pts = 26 if small else (36 if rank == 1 else 30)
    draw.text((WIDTH - 50, middle), f"{player.points:,} PTS",
              font=font("title", size_pts, "SemiBold"), fill=BLUE,
              anchor="rm")  # fmt: skip
