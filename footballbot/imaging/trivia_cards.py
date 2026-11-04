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
    BLUE_DEEP,
    LINE,
    MUTED,
    PANEL,
    RGB,
    TEXT,
    avatar,
    brand,
    fit_font,
    font,
    hex_texture,
    logo,
    paste,
    tile,
    to_png,
    truncate,
    wordmark,
)

WIDTH = 800
# El 3er puesto del podio: un azul oscuro, para que se vea sobre el negro sin competir
THIRD: RGB = (22, 46, 96)


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
) -> bytes:
    """Una ronda: "ROUND 3/10", la imagen en un marco, la pregunta y la barra de etapas."""
    height = 740
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    hex_texture(canvas, (0, 0, WIDTH, 126))
    draw = ImageDraw.Draw(canvas)
    draw.text((36, 50), f"ROUND {round_no}/{total_rounds}", font=font("title", 46, "Bold"),
              fill=TEXT, anchor="lm")  # fmt: skip
    draw.text((38, 98), title.upper(), font=font("title", 24, "SemiBold"), fill=BLUE,
              anchor="lm")  # fmt: skip
    brand(canvas, right=WIDTH - 28, top=22, size=118)
    draw.rectangle((0, 124, WIDTH, 127), fill=BLUE)

    # La imagen de la etapa en un marco recto azul
    size = 432
    left, top = (WIDTH - size) // 2, 150
    draw.rectangle((left - 4, top - 4, left + size + 3, top + size + 3), fill=BLUE)
    image = Image.open(io.BytesIO(stage_image)).convert("RGBA").resize((size, size))
    canvas.paste(image, (left, top))

    # La pregunta, grande, debajo de la imagen
    if prompt:
        prompt_font = fit_font(prompt.upper(), "title", "SemiBold", 34, WIDTH - 80, 22)
        draw.text((WIDTH // 2, 624), prompt.upper(), font=prompt_font, fill=TEXT, anchor="mm")

    # Barra de etapas: la actual en azul, las pasadas tachadas, las que vienen solo con borde
    gap = 10
    segment = (WIDTH - 72 - gap * (len(points) - 1)) // len(points)
    y0, y1 = 670, 712
    for i, value in enumerate(points):
        x0 = 36 + i * (segment + gap)
        box = (x0, y0, x0 + segment, y1)
        if i == stage:
            draw.rectangle(box, fill=BLUE)
            color = TEXT
        elif i < stage:
            draw.rectangle(box, fill=PANEL)
            color = MUTED
            # Tachado: esos puntos ya no se pueden ganar
            mid = (y0 + y1) // 2
            draw.line((x0 + segment // 2 - 38, mid, x0 + segment // 2 + 38, mid), fill=MUTED,
                      width=2)  # fmt: skip
        else:
            draw.rectangle(box, outline=LINE, width=2)
            color = MUTED
        draw.text((x0 + segment // 2, (y0 + y1) // 2), f"{value} PTS",
                  font=font("title", 22, "SemiBold"), fill=color, anchor="mm")  # fmt: skip
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
) -> bytes:
    """La respuesta: escudo limpio, nombre, "País · Liga" y quién acertó (o que nadie)."""
    height = 600
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    # El logo del bot, grande y muy tenue, saliendo por la esquina de abajo a la derecha
    paste(canvas, logo(520, opacity=0.08), (WIDTH - 360, height - 300))
    draw = ImageDraw.Draw(canvas)
    if label:
        draw.text((36, 40), label.upper(), font=font("title", 24, "SemiBold"), fill=BLUE,
                  anchor="lm")  # fmt: skip
    brand(canvas, right=WIDTH - 28, top=18, size=86)
    wordmark(draw, (36, height - 26), anchor="lm")

    cx = WIDTH // 2
    tile(canvas, crest, (cx - 125, 78, cx + 125, 328), border=BLUE)

    name_font = fit_font(name.upper(), "title", "Bold", 60, WIDTH - 80, 28)
    draw.text((cx, 392), name.upper(), font=name_font, fill=TEXT, anchor="mm")
    if subtitle:
        draw.text((cx, 440), subtitle, font=font("text", 24, "Medium"), fill=MUTED, anchor="mm")

    # Resultado en una barra recta: azul si alguien acertó, gris si no
    bar_font = font("title", 28, "SemiBold")
    text = truncate(headline.upper(), bar_font, WIDTH - 240)
    bar_w = int(bar_font.getlength(text)) + 80
    box = (cx - bar_w // 2, 492, cx + bar_w // 2, 548)
    if success:
        draw.rectangle(box, fill=BLUE)
        draw.text((cx, 520), text, font=bar_font, fill=TEXT, anchor="mm")
    else:
        draw.rectangle(box, outline=LINE, width=2)
        draw.text((cx, 520), text, font=bar_font, fill=MUTED, anchor="mm")
    return to_png(canvas)


# --- podio y ranking ---------------------------------------------------------------------------


def podium_card(*, title: str, subtitle: str, players: Sequence[PlayerEntry]) -> bytes:
    """Final de la partida: podio con avatares para los 3 primeros y la lista del resto."""
    rest = list(players[3:10])
    row_h = 56
    height = 620 + (len(rest) * row_h + 30 if rest else 0)
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    paste(canvas, logo(520, opacity=0.07), (WIDTH - 380, 250))
    draw = ImageDraw.Draw(canvas)
    _header(canvas, draw, title, subtitle)

    # Orden visual del podio: 2º a la izquierda, 1º al centro, 3º a la derecha.
    # El 1º en azul, el 2º en azul profundo y el 3º en panel con borde.
    floor = 580
    spots = ((1, 210, 170, BLUE_DEEP), (0, 400, 240, BLUE), (2, 590, 120, THIRD))
    for place, x, block_h, fill in spots:
        if place >= len(players):
            continue
        player = players[place]
        top = floor - block_h
        draw.rectangle((x - 92, top, x + 92, floor), fill=fill)
        draw.text((x, top + 44), str(place + 1), font=font("title", 60, "Bold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
        draw.text((x, top + 96), f"{player.points} PTS", font=font("title", 24, "SemiBold"),
                  fill=TEXT, anchor="mm")  # fmt: skip
        size = 104 if place == 0 else 88
        ay = top - 34 - size // 2 - 30
        ring = size // 2 + 4
        draw.ellipse((x - ring, ay - ring, x + ring, ay + ring), fill=BLUE if place == 0 else LINE)
        picture = avatar(player.avatar, size, player.name, fill=BLUE_DEEP)
        canvas.paste(picture, (x - size // 2, ay - size // 2), picture)
        name_font = font("text", 23, "SemiBold")
        draw.text((x, ay + ring + 20), truncate(player.name, name_font, 190), font=name_font,
                  fill=TEXT, anchor="mm")  # fmt: skip

    if rest:
        y = floor + 30
        for i, player in enumerate(rest, start=4):
            _player_row(canvas, draw, y, row_h, i, player, small=True)
            y += row_h
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


def _header(canvas: Image.Image, draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    """Cabecera del podio y del ranking: título, subtítulo, el logo del bot y la línea azul."""
    hex_texture(canvas, (0, 0, WIDTH, 126))
    draw.text((36, 50), title.upper(), font=font("title", 48, "Bold"), fill=TEXT, anchor="lm")
    draw.text((38, 98), subtitle, font=font("text", 22, "Medium"), fill=MUTED, anchor="lm")
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
        draw.rectangle((44, middle - 19, 82, middle + 19), fill=BLUE if rank == 1 else BLUE_DEEP)
        draw.text((63, middle), str(rank), font=font("title", 24, "Bold"), fill=TEXT,
                  anchor="mm")  # fmt: skip
    else:
        draw.text((63, middle), str(rank), font=font("title", 26, "SemiBold"), fill=MUTED,
                  anchor="mm")  # fmt: skip
    size = row_h - (22 if small else 20)
    picture = avatar(player.avatar, size, player.name, fill=BLUE_DEEP)
    canvas.paste(picture, (104, middle - size // 2), picture)
    name_font = font("text", 22 if small else 26, "SemiBold")
    text_x = 104 + size + 18
    if player.detail and not small:
        draw.text((text_x, middle - 13), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
        draw.text((text_x, middle + 17), player.detail, font=font("text", 18), fill=MUTED,
                  anchor="lm")  # fmt: skip
    else:
        draw.text((text_x, middle), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
    draw.text((WIDTH - 50, middle), f"{player.points:,} PTS",
              font=font("title", 26 if small else 30, "SemiBold"), fill=BLUE,
              anchor="rm")  # fmt: skip
