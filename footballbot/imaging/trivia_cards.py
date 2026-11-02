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
    BG_BOTTOM,
    BG_TOP,
    MEDALS,
    MUTED,
    RGB,
    ROW_A,
    ROW_B,
    TEXT,
    accent_band,
    avatar,
    fit_font,
    font,
    load_icon,
    mix,
    paste_icon,
    pill,
    readable_on,
    to_png,
    truncate,
    vertical_gradient,
)

WIDTH = 800
DIM: RGB = (52, 58, 74)  # etapas que ya pasaron
SUBTITLE: RGB = (214, 218, 228)  # se lee sobre cualquier color de banda


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
    accent: RGB,
    stage: int,
    points: Sequence[int],
) -> bytes:
    """Una ronda: "ROUND 3/10", la imagen con el efecto en un marco y la barra de etapas."""
    height = 680
    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    canvas.paste(accent_band((WIDTH, 96), accent), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((40, 50), f"ROUND {round_no}/{total_rounds}", font=font("title", 46, "Bold"),
              fill=TEXT, anchor="lm")  # fmt: skip
    draw.text((WIDTH - 40, 50), title.upper(), font=font("title", 28, "SemiBold"),
              fill=mix(accent, TEXT, 0.5), anchor="rm")  # fmt: skip

    # La imagen de la etapa en un marco redondeado del color del modo
    size = 440
    left, top = (WIDTH - size) // 2, 124
    draw.rounded_rectangle((left - 8, top - 8, left + size + 8, top + size + 8), radius=34,
                           fill=accent)  # fmt: skip
    image = Image.open(io.BytesIO(stage_image)).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=28, fill=255)
    canvas.paste(image, (left, top), mask)

    # Barra de etapas: la actual con el color del modo, las pasadas apagadas
    gap = 12
    segment = (WIDTH - 80 - gap * (len(points) - 1)) // len(points)
    y0, y1 = 610, 654
    for i, value in enumerate(points):
        x0 = 40 + i * (segment + gap)
        if i == stage:
            fill, label_color = accent, readable_on(accent)
        else:
            fill, label_color = (DIM if i < stage else ROW_A), MUTED
        draw.rounded_rectangle((x0, y0, x0 + segment, y1), radius=12, fill=fill)
        draw.text((x0 + segment // 2, (y0 + y1) // 2), f"{value} PTS",
                  font=font("title", 24, "SemiBold"), fill=label_color,
                  anchor="mm")  # fmt: skip
    return to_png(canvas)


# --- respuesta ---------------------------------------------------------------------------------


def reveal_card(
    *,
    crest: bytes,
    name: str,
    subtitle: str | None,
    accent: RGB,
    headline: str,
    success: bool,
) -> bytes:
    """La respuesta: escudo limpio, nombre, "País · Liga" y quién acertó (o que nadie)."""
    height = 600
    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    canvas.paste(accent_band((WIDTH, 96), accent), (0, 0))
    draw = ImageDraw.Draw(canvas)

    cx, cy = WIDTH // 2, 210
    for radius, fill in ((150, accent), (138, (236, 238, 243))):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)
    paste_icon(canvas, load_icon(crest, 210), (cx, cy))

    name_font = fit_font(name.upper(), "title", "Bold", 60, WIDTH - 80, 28)
    draw.text((cx, 410), name.upper(), font=name_font, fill=TEXT, anchor="mm")
    if subtitle:
        draw.text((cx, 462), subtitle, font=font("text", 26, "Medium"), fill=MUTED, anchor="mm")

    chip_font = font("title", 30, "SemiBold")
    text = truncate(headline.upper(), chip_font, WIDTH - 200)
    chip_w = int(chip_font.getlength(text)) + 64
    color = (52, 199, 89) if success else (90, 96, 112)
    pill(draw, (cx - chip_w // 2, 506, cx + chip_w // 2, 562), color, text, chip_font)
    return to_png(canvas)


# --- podio y ranking ---------------------------------------------------------------------------


def podium_card(*, title: str, subtitle: str, accent: RGB, players: Sequence[PlayerEntry]) -> bytes:
    """Final de la partida: podio con avatares para los 3 primeros y la lista del resto."""
    rest = list(players[3:10])
    row_h = 56
    height = 640 + (len(rest) * row_h + 30 if rest else 0)
    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    canvas.paste(accent_band((WIDTH, 110), accent), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((40, 48), title.upper(), font=font("title", 50, "Bold"), fill=TEXT, anchor="lm")
    draw.text((42, 92), subtitle, font=font("text", 22, "Medium"), fill=SUBTITLE, anchor="lm")

    # Orden visual del podio: 2º a la izquierda, 1º al centro, 3º a la derecha
    floor = 600
    spots = ((1, 200, 170), (0, 400, 240), (2, 600, 120))  # (puesto, centro x, alto)
    for place, x, block_h in spots:
        if place >= len(players):
            continue
        player = players[place]
        medal = MEDALS[place]
        top = floor - block_h
        draw.rounded_rectangle((x - 95, top, x + 95, floor), radius=18,
                               fill=mix(medal, BG_BOTTOM, 0.55))  # fmt: skip
        draw.text((x, top + 46), str(place + 1), font=font("title", 64, "Bold"), fill=medal,
                  anchor="mm")  # fmt: skip
        if block_h > 130:
            draw.text((x, top + 100), f"{player.points} PTS", font=font("title", 26, "SemiBold"),
                      fill=TEXT, anchor="mm")  # fmt: skip
        size = 110 if place == 0 else 92
        ring = size // 2 + 6
        ay = top - 30 - size // 2 - 34
        draw.ellipse((x - ring, ay - ring, x + ring, ay + ring), fill=medal)
        picture = avatar(player.avatar, size, player.name)
        canvas.paste(picture, (x - size // 2, ay - size // 2), picture)
        name_font = font("text", 24, "SemiBold")
        draw.text((x, ay + ring + 22), truncate(player.name, name_font, 200), font=name_font,
                  fill=TEXT, anchor="mm")  # fmt: skip
        if block_h <= 130:
            draw.text((x, top + 96), f"{player.points} PTS", font=font("title", 22, "SemiBold"),
                      fill=TEXT, anchor="mm")  # fmt: skip

    if rest:
        y = floor + 30
        for i, player in enumerate(rest, start=4):
            _player_row(canvas, draw, y, row_h, i, player, small=True)
            y += row_h
    return to_png(canvas)


def leaderboard_card(
    *, title: str, subtitle: str, accent: RGB, players: Sequence[PlayerEntry]
) -> bytes:
    """El ranking del servidor: medalla, avatar, nombre, aciertos y puntos de cada jugador."""
    row_h = 76
    height = 140 + len(players) * row_h + 30
    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    canvas.paste(accent_band((WIDTH, 120), accent), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((40, 52), title.upper(), font=font("title", 50, "Bold"), fill=TEXT, anchor="lm")
    draw.text((42, 98), subtitle, font=font("text", 22, "Medium"), fill=SUBTITLE, anchor="lm")
    y = 140
    for i, player in enumerate(players, start=1):
        _player_row(canvas, draw, y, row_h, i, player)
        y += row_h
    return to_png(canvas)


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
    draw.rounded_rectangle((32, y + 4, WIDTH - 32, y + row_h - 4), radius=14,
                           fill=ROW_A if rank % 2 else ROW_B)  # fmt: skip
    # Puesto: círculo de medalla para los 3 primeros, número para el resto
    if rank <= len(MEDALS):
        draw.ellipse((52, middle - 20, 92, middle + 20), fill=MEDALS[rank - 1])
        draw.text((72, middle), str(rank), font=font("title", 24, "Bold"), fill=(20, 22, 28),
                  anchor="mm")  # fmt: skip
    else:
        draw.text((72, middle), str(rank), font=font("title", 26, "SemiBold"), fill=MUTED,
                  anchor="mm")  # fmt: skip
    size = row_h - (22 if small else 20)
    picture = avatar(player.avatar, size, player.name)
    canvas.paste(picture, (110, middle - size // 2), picture)
    name_font = font("text", 22 if small else 26, "SemiBold")
    text_x = 110 + size + 18
    if player.detail and not small:
        draw.text((text_x, middle - 13), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
        draw.text((text_x, middle + 17), player.detail, font=font("text", 18), fill=MUTED,
                  anchor="lm")  # fmt: skip
    else:
        draw.text((text_x, middle), truncate(player.name, name_font, 380), font=name_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
    draw.text((WIDTH - 56, middle), f"{player.points:,} PTS",
              font=font("title", 26 if small else 30, "SemiBold"), fill=TEXT,
              anchor="rm")  # fmt: skip
