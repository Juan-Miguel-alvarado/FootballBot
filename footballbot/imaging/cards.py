"""Tarjetas generadas como imagen: tabla de posiciones y perfil de equipo (issue #10).

Las funciones reciben los datos ya preparados (nombres, colores de zona, escudos en bytes) y
devuelven un PNG. No saben de la API ni de Discord: cogs/info.py arma los datos, baja los
escudos y llama aquí con `asyncio.to_thread` (Pillow bloquea).

Estilo "Fragmentos azules" (el del logo del bot): ver imaging/draw.py para colores, fuentes y
las piezas del logo. Para cambiar el look de todas las tarjetas, empieza por draw.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from footballbot.imaging.draw import (
    BLACK,
    BLUE,
    DRAW,
    LINE,
    LOSS,
    MUTED,
    PANEL,
    RGB,
    TEXT,
    WIN,
    brand,
    fit_font,
    font,
    hex_texture,
    logo,
    paste,
    shards,
    tile,
    to_png,
    truncate,
    wordmark,
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
FOOTER_H = 50
# Centro de cada columna de números
STAT_X = {"P": 600, "W": 648, "D": 696, "L": 744, "GD": 802, "PTS": 860}


def standings_card(
    *,
    title: str,
    subtitle: str,
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

    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    _header(canvas, title, subtitle, emblem)
    draw = ImageDraw.Draw(canvas)

    # Títulos de las columnas
    y = HEADER_H
    label_font = font("text", 17, "SemiBold")
    middle = y + COLUMNS_H // 2
    draw.text((62, middle), "#", font=label_font, fill=MUTED, anchor="mm")
    draw.text((140, middle), "TEAM", font=label_font, fill=MUTED, anchor="lm")
    for label, x in STAT_X.items():
        draw.text((x, middle), label, font=label_font, fill=MUTED, anchor="mm")
    y += COLUMNS_H

    name_font = font("text", 24 if row_h > 40 else 22, "SemiBold")
    stat_font = font("text", 22 if row_h > 40 else 20, "Regular")
    pts_font = font("text", 24 if row_h > 40 else 22, "Bold")
    for group in groups:
        if group.title:
            draw.rectangle((24, y + 18, 30, y + GROUP_TITLE_H - 10), fill=BLUE)
            draw.text((42, y + GROUP_TITLE_H // 2 + 4), group.title.upper(),
                      font=font("title", 26, "SemiBold"), fill=TEXT, anchor="lm")  # fmt: skip
            y += GROUP_TITLE_H
        for i, row in enumerate(group.rows):
            _table_row(canvas, draw, row, y, row_h, i % 2 == 0,
                       name_font, stat_font, pts_font)  # fmt: skip
            y += row_h

    if legend_lines:
        y += 16
        for line in legend_lines:
            x = 30
            for color, label in line:
                draw.rectangle((x, y + 13, x + 14, y + 27), fill=color)
                draw.text((x + 24, y + 20), label, font=font("text", 20, "Medium"),
                          fill=TEXT, anchor="lm")  # fmt: skip
                x += 24 + int(font("text", 20, "Medium").getlength(label)) + 34
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
    name_font: ImageFont.FreeTypeFont,
    stat_font: ImageFont.FreeTypeFont,
    pts_font: ImageFont.FreeTypeFont,
) -> None:
    middle = y + row_h // 2
    if even:
        draw.rectangle((24, y, WIDTH - 24, y + row_h - 1), fill=PANEL)
    if row.zone_color:
        # Franja fina a la izquierda: dice la zona (Champions, descenso...)
        draw.rectangle((24, y, 28, y + row_h - 1), fill=row.zone_color)
    draw.text((62, middle), str(row.position), font=stat_font, fill=TEXT, anchor="mm")
    # Cuadro claro detrás del escudo: así se ven los escudos oscuros sobre el negro
    side = row_h - 14
    tile(canvas, row.crest, (90, middle - side // 2, 90 + side, middle + side // 2))
    draw.text((140, middle), truncate(row.name, name_font, 420), font=name_font, fill=TEXT,
              anchor="lm")  # fmt: skip
    gd = f"{row.goal_difference:+d}" if row.goal_difference else "0"
    stats = {"P": row.played, "W": row.won, "D": row.draw, "L": row.lost, "GD": gd}
    for label, value in stats.items():
        draw.text((STAT_X[label], middle), str(value), font=stat_font, fill=MUTED, anchor="mm")
    draw.text((STAT_X["PTS"], middle), str(row.points), font=pts_font, fill=BLUE, anchor="mm")


def _legend_lines(legend: Sequence[tuple[RGB, str]]) -> list[list[tuple[RGB, str]]]:
    """Reparte la leyenda en renglones que quepan en el ancho de la tarjeta."""
    lines: list[list[tuple[RGB, str]]] = []
    current: list[tuple[RGB, str]] = []
    used = 30
    label_font = font("text", 20, "Medium")
    for color, label in legend:
        size = 24 + int(label_font.getlength(label)) + 34
        if current and used + size > WIDTH - 30:
            lines.append(current)
            current, used = [], 30
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
    facts: Sequence[tuple[str, str]],
    form: Sequence[str] = (),
    last_result: str | None = None,
    next_match: NextMatch | None = None,
) -> bytes:
    """Perfil del equipo: escudo grande, datos, racha W/D/L y el próximo partido tipo "versus"."""
    height = 640
    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    # El logo del bot, grande y muy tenue, saliendo por la esquina de abajo a la derecha
    paste(canvas, logo(560, opacity=0.09), (WIDTH - 420, height - 330))
    # Fragmentos del logo saliendo por la esquina de arriba
    paste(canvas, shards(96, opacity=0.9), (WIDTH - 120, 22))
    draw = ImageDraw.Draw(canvas)

    tile(canvas, crest, (44, 44, 290, 290), border=BLUE)

    title_font = fit_font(name.upper(), "title", "Bold", 64, 470, 30)
    draw.text((330, 82), name.upper(), font=title_font, fill=TEXT, anchor="lm")
    draw.text((332, 136), subtitle, font=font("text", 24, "Medium"), fill=MUTED, anchor="lm")

    y = 190
    for label, value in facts[:4]:
        draw.text((332, y), label.upper(), font=font("text", 16, "SemiBold"), fill=MUTED,
                  anchor="lm")  # fmt: skip
        value_font = font("text", 22, "SemiBold")
        draw.text((500, y), truncate(value, value_font, 370), font=value_font, fill=TEXT,
                  anchor="lm")  # fmt: skip
        y += 37

    # Separador: línea fina con un tramo azul
    draw.rectangle((40, 336, WIDTH - 40, 337), fill=LINE)
    draw.rectangle((40, 335, 160, 338), fill=BLUE)

    # Racha: cuadrados rectos (ganó azul, empató gris, perdió rojo apagado)
    draw.text((40, 380), "FORM", font=font("title", 24, "SemiBold"), fill=MUTED, anchor="lm")
    if form:
        x = 40
        for result in form:
            draw.rectangle((x, 406, x + 54, 460), fill=FORM_COLORS.get(result, DRAW))
            draw.text((x + 27, 433), result, font=font("title", 28, "Bold"), fill=TEXT,
                      anchor="mm")  # fmt: skip
            x += 62
    else:
        draw.text((40, 433), "No recent matches", font=font("text", 22), fill=MUTED, anchor="lm")
    if last_result:
        draw.text((40, 494), truncate(f"Last: {last_result}", font("text", 20), 420),
                  font=font("text", 20), fill=MUTED, anchor="lm")  # fmt: skip

    # Próximo partido estilo "versus": los dos escudos en cuadros claros
    draw.text((500, 380), "NEXT MATCH", font=font("title", 24, "SemiBold"), fill=MUTED,
              anchor="lm")  # fmt: skip
    if next_match:
        for crest_bytes, x in ((next_match.home_crest, 545), (next_match.away_crest, 800)):
            tile(canvas, crest_bytes, (x - 38, 410, x + 38, 486))
        draw.text((672, 448), "VS", font=font("title", 38, "Bold"), fill=BLUE, anchor="mm")
        where = "vs" if next_match.home else "at"
        line_font = font("text", 22, "SemiBold")
        draw.text((672, 522), truncate(f"{where} {next_match.opponent}", line_font, 380),
                  font=line_font, fill=TEXT, anchor="mm")  # fmt: skip
        draw.text((672, 552), f"{next_match.when} · {next_match.competition}",
                  font=font("text", 18), fill=MUTED, anchor="mm")  # fmt: skip
    else:
        draw.text((500, 433), "No match scheduled", font=font("text", 22), fill=MUTED,
                  anchor="lm")  # fmt: skip

    _footer(draw, height)
    return to_png(canvas)


# --- partes comunes ----------------------------------------------------------------------------


def _header(canvas: Image.Image, title: str, subtitle: str, emblem: bytes | None) -> None:
    """Cabecera: logo de la competición, nombre, subtítulo y la marca del bot a la derecha."""
    hex_texture(canvas, (0, 0, WIDTH, HEADER_H - 4))
    tile(canvas, emblem, (32, 28, 124, 120))
    draw = ImageDraw.Draw(canvas)
    title_font = fit_font(title.upper(), "title", "Bold", 54, WIDTH - 340, 28)
    draw.text((150, 64), title.upper(), font=title_font, fill=TEXT, anchor="lm")
    draw.text((152, 112), subtitle, font=font("text", 22, "Medium"), fill=MUTED, anchor="lm")
    brand(canvas, right=WIDTH - 28, top=30, size=128)
    # Línea azul que cierra la cabecera
    draw.rectangle((0, HEADER_H - 4, WIDTH, HEADER_H - 1), fill=BLUE)


def _footer(draw: ImageDraw.ImageDraw, height: int) -> None:
    """Pie: la firma del bot a la izquierda y la fuente de los datos a la derecha."""
    y = height - FOOTER_H // 2
    wordmark(draw, (30, y), anchor="lm")
    draw.text((WIDTH - 30, y), SOURCE, font=font("text", 16), fill=(90, 99, 116), anchor="rm")
