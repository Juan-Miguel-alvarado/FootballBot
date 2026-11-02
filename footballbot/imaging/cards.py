"""Tarjetas generadas como imagen: tabla de posiciones y perfil de equipo (issue #10).

Las funciones reciben los datos ya preparados (nombres, colores de zona, escudos en bytes) y
devuelven un PNG. No saben de la API ni de Discord: cogs/info.py arma los datos, baja los
escudos y llama aquí con `asyncio.to_thread` (Pillow bloquea).

Para cambiar el estilo de todas las tarjetas (colores, fuentes) mira imaging/draw.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from footballbot.imaging.draw import (
    BG_BOTTOM,
    BG_TOP,
    DRAW,
    LOSS,
    MUTED,
    RGB,
    ROW_A,
    ROW_B,
    TEXT,
    WIN,
    accent_band,
    fade_mask,
    fit_font,
    font,
    load_icon,
    mix,
    paste_icon,
    to_png,
    truncate,
    vertical_gradient,
)

WIDTH = 900
SOURCE = "Data: football-data.org"
FORM_COLORS = {"W": WIN, "D": DRAW, "L": LOSS}


# --- tabla de posiciones -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TableRow:
    """Una fila de la tarjeta de posiciones, ya con su color de zona."""

    position: int
    name: str
    crest: bytes | None
    played: int
    won: int
    draw: int
    lost: int
    goal_difference: int
    points: int
    zone_color: RGB | None = None


@dataclass(frozen=True, slots=True)
class TableGroup:
    """Una tabla. Las ligas tienen una sola (title=None); los torneos, una por grupo."""

    title: str | None
    rows: tuple[TableRow, ...]


HEADER_H = 150
COLUMNS_H = 44
GROUP_TITLE_H = 52
LEGEND_LINE_H = 40
FOOTER_H = 44
# Centro de cada columna de números
STAT_X = {"P": 600, "W": 648, "D": 696, "L": 744, "GD": 802, "PTS": 860}


def standings_card(
    *,
    title: str,
    subtitle: str,
    accent: RGB,
    emblem: bytes | None,
    groups: Sequence[TableGroup],
    legend: Sequence[tuple[RGB, str]] = (),
) -> bytes:
    """La tabla como imagen: cabecera con el logo, filas con escudo y franja de zona, leyenda."""
    total_rows = sum(len(g.rows) for g in groups)
    row_h = 46 if total_rows <= 24 else 40
    group_titles = sum(1 for g in groups if g.title)
    legend_lines = _legend_lines(legend)
    height = (
        HEADER_H
        + COLUMNS_H
        + total_rows * row_h
        + group_titles * GROUP_TITLE_H
        + len(legend_lines) * LEGEND_LINE_H
        + (16 if legend_lines else 0)
        + FOOTER_H
    )

    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    _header(canvas, title, subtitle, accent, emblem)
    draw = ImageDraw.Draw(canvas)

    # Títulos de las columnas
    y = HEADER_H
    label_font = font("text", 18, "SemiBold")
    draw.text((62, y + COLUMNS_H // 2), "#", font=label_font, fill=MUTED, anchor="mm")
    draw.text((140, y + COLUMNS_H // 2), "TEAM", font=label_font, fill=MUTED, anchor="lm")
    for label, x in STAT_X.items():
        draw.text((x, y + COLUMNS_H // 2), label, font=label_font, fill=MUTED, anchor="mm")
    y += COLUMNS_H

    name_font = font("text", 24 if row_h > 40 else 22, "SemiBold")
    stat_font = font("text", 22 if row_h > 40 else 20, "Regular")
    pts_font = font("text", 24 if row_h > 40 else 22, "Bold")
    crest_size = row_h - 12
    for group in groups:
        if group.title:
            draw.text(
                (40, y + GROUP_TITLE_H // 2 + 4),
                group.title.upper(),
                font=font("title", 28, "SemiBold"),
                fill=mix(accent, TEXT, 0.55),
                anchor="lm",
            )
            y += GROUP_TITLE_H
        for i, row in enumerate(group.rows):
            _table_row(canvas, draw, row, y, row_h, i % 2 == 0, crest_size,
                       name_font, stat_font, pts_font)  # fmt: skip
            y += row_h

    if legend_lines:
        y += 16
        for line in legend_lines:
            x = 40
            for color, label in line:
                draw.ellipse((x, y + 12, x + 16, y + 28), fill=color)
                draw.text((x + 26, y + 20), label, font=font("text", 20, "Medium"),
                          fill=TEXT, anchor="lm")  # fmt: skip
                x += 26 + int(font("text", 20, "Medium").getlength(label)) + 34
            y += LEGEND_LINE_H

    _footer(draw, height)
    return to_png(canvas)


def _table_row(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    row: TableRow,
    y: int,
    row_h: int,
    even: bool,
    crest_size: int,
    name_font: ImageFont.FreeTypeFont,
    stat_font: ImageFont.FreeTypeFont,
    pts_font: ImageFont.FreeTypeFont,
) -> None:
    middle = y + row_h // 2
    draw.rectangle((24, y, WIDTH - 24, y + row_h - 2), fill=ROW_A if even else ROW_B)
    if row.zone_color:
        # Franja de color a la izquierda: dice la zona (Champions, descenso...)
        draw.rectangle((24, y, 31, y + row_h - 2), fill=row.zone_color)
    draw.text((62, middle), str(row.position), font=stat_font, fill=TEXT, anchor="mm")
    # Círculo claro detrás del escudo: así se ven los escudos oscuros sobre el fondo oscuro
    cx = 106
    r = crest_size // 2 + 3
    draw.ellipse((cx - r, middle - r, cx + r, middle + r), fill=(232, 235, 241))
    paste_icon(canvas, load_icon(row.crest, crest_size - 6), (cx, middle))
    name = truncate(row.name, name_font, 420)
    draw.text((140, middle), name, font=name_font, fill=TEXT, anchor="lm")
    gd = f"{row.goal_difference:+d}" if row.goal_difference else "0"
    stats = {"P": row.played, "W": row.won, "D": row.draw, "L": row.lost, "GD": gd}
    for label, value in stats.items():
        draw.text((STAT_X[label], middle), str(value), font=stat_font, fill=MUTED, anchor="mm")
    draw.text((STAT_X["PTS"], middle), str(row.points), font=pts_font, fill=TEXT, anchor="mm")


def _legend_lines(legend: Sequence[tuple[RGB, str]]) -> list[list[tuple[RGB, str]]]:
    """Reparte la leyenda en renglones que quepan en el ancho de la tarjeta."""
    lines: list[list[tuple[RGB, str]]] = []
    current: list[tuple[RGB, str]] = []
    used = 40
    label_font = font("text", 20, "Medium")
    for color, label in legend:
        size = 26 + int(label_font.getlength(label)) + 34
        if current and used + size > WIDTH - 40:
            lines.append(current)
            current, used = [], 40
        current.append((color, label))
        used += size
    if current:
        lines.append(current)
    return lines


# --- perfil de equipo --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NextMatch:
    home_crest: bytes | None
    away_crest: bytes | None
    opponent: str
    home: bool  # True si nuestro equipo juega de local
    when: str  # "Sun 25 Oct · 15:00"
    competition: str


def team_card(
    *,
    name: str,
    subtitle: str,
    crest: bytes | None,
    accent: RGB,
    facts: Sequence[tuple[str, str]],
    form: Sequence[str] = (),
    last_result: str | None = None,
    next_match: NextMatch | None = None,
) -> bytes:
    """Perfil del equipo: escudo grande, datos, racha W/D/L y el próximo partido tipo "versus"."""
    height = 640
    canvas = vertical_gradient((WIDTH, height), BG_TOP, BG_BOTTOM).convert("RGBA")
    # Banda de color del club arriba, que se desvanece hacia abajo (sin borde duro)
    band = accent_band((WIDTH, 380), accent).convert("RGBA")
    band.putalpha(fade_mask(band.size, start=0.45))
    canvas.alpha_composite(band)
    draw = ImageDraw.Draw(canvas)

    # Escudo grande sobre un disco claro con un aro del color del club
    # (el disco claro hace que se vean también los escudos negros, como el de la Juventus)
    for radius, fill in ((134, accent), (122, (236, 238, 243))):
        draw.ellipse((170 - radius, 175 - radius, 170 + radius, 175 + radius), fill=fill)
    paste_icon(canvas, load_icon(crest, 190), (170, 175))

    title_font = fit_font(name.upper(), "title", "Bold", 64, 530, 30)
    draw.text((330, 85), name.upper(), font=title_font, fill=TEXT, anchor="lm")
    draw.text((332, 140), subtitle, font=font("text", 24, "Medium"), fill=MUTED, anchor="lm")

    y = 192
    for label, value in facts[:4]:
        draw.text((332, y), label.upper(), font=font("text", 17, "SemiBold"), fill=MUTED,
                  anchor="lm")  # fmt: skip
        value_font = font("text", 23, "SemiBold")
        draw.text((500, y), truncate(value, value_font, 370), font=value_font, fill=TEXT,
                  anchor="lm")  # fmt: skip
        y += 38

    draw.line((40, 380, WIDTH - 40, 380), fill=(55, 62, 78), width=2)

    # Racha: cuadritos de colores con W/D/L
    draw.text((40, 415), "FORM", font=font("title", 26, "SemiBold"), fill=MUTED, anchor="lm")
    if form:
        x = 40
        for result in form:
            color = FORM_COLORS.get(result, MUTED)
            draw.rounded_rectangle((x, 440, x + 56, 496), radius=10, fill=color)
            draw.text((x + 28, 468), result, font=font("title", 30, "Bold"),
                      fill=(20, 22, 28), anchor="mm")  # fmt: skip
            x += 66
    else:
        draw.text((40, 468), "No recent matches", font=font("text", 22), fill=MUTED, anchor="lm")
    if last_result:
        draw.text((40, 530), truncate(f"Last: {last_result}", font("text", 20), 430),
                  font=font("text", 20), fill=MUTED, anchor="lm")  # fmt: skip

    # Próximo partido estilo "versus": nuestro escudo y el del rival
    draw.text((490, 415), "NEXT MATCH", font=font("title", 26, "SemiBold"), fill=MUTED,
              anchor="lm")  # fmt: skip
    if next_match:
        for crest_bytes, x in ((next_match.home_crest, 545), (next_match.away_crest, 785)):
            draw.ellipse((x - 42, 470 - 42, x + 42, 470 + 42), fill=(232, 235, 241))
            paste_icon(canvas, load_icon(crest_bytes, 64), (x, 470))
        draw.text((665, 470), "VS", font=font("title", 40, "Bold"), fill=TEXT, anchor="mm")
        where = "vs" if next_match.home else "at"
        line = f"{where} {next_match.opponent}"
        draw.text((665, 538), truncate(line, font("text", 22, "SemiBold"), 380),
                  font=font("text", 22, "SemiBold"), fill=TEXT, anchor="mm")  # fmt: skip
        draw.text((665, 570), f"{next_match.when} · {next_match.competition}",
                  font=font("text", 18), fill=MUTED, anchor="mm")  # fmt: skip
    else:
        draw.text((490, 468), "No match scheduled", font=font("text", 22), fill=MUTED,
                  anchor="lm")  # fmt: skip

    _footer(draw, height)
    return to_png(canvas)


# --- partes comunes ----------------------------------------------------------------------------


def _header(
    canvas: Image.Image, title: str, subtitle: str, accent: RGB, emblem: bytes | None
) -> None:
    canvas.paste(accent_band((WIDTH, HEADER_H), accent), (0, 0))
    draw = ImageDraw.Draw(canvas)
    # Logo sobre un cuadro claro redondeado (hay logos oscuros que no se ven sobre el fondo)
    draw.rounded_rectangle((32, 22, 138, 128), radius=22, fill=(240, 242, 247))
    paste_icon(canvas, load_icon(emblem, 86), (85, 75))
    title_font = fit_font(title.upper(), "title", "Bold", 54, WIDTH - 200, 28)
    draw.text((164, 62), title.upper(), font=title_font, fill=TEXT, anchor="lm")
    draw.text((166, 112), subtitle, font=font("text", 24, "Medium"), fill=MUTED, anchor="lm")


def _footer(draw: ImageDraw.ImageDraw, height: int) -> None:
    draw.text((WIDTH - 32, height - FOOTER_H // 2), SOURCE, font=font("text", 16),
              fill=(110, 117, 133), anchor="rm")  # fmt: skip
