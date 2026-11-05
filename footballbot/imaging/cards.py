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
    RGB,
    TEXT,
    WIN,
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
COLUMNS_H = 48
GROUP_TITLE_H = 52
LEGEND_LINE_H = 44
FOOTER_H = 50
# Centro de cada columna de números. Ganados-empatados-perdidos van juntos ("12-3-4"):
# tres columnas estrechas se leían mal en el celular
STAT_X = {"P": 562, "W-D-L": 666, "GD": 772, "PTS": 844}
# Signo menos tipográfico para la diferencia de goles (más ancho que el guion "-")
MINUS = "\u2212"
# Los números de la tabla (partidos, W-D-L, GD): más claros que MUTED, se leen mejor
STAT_COLOR: RGB = (184, 192, 206)
# Filas alternas: un poco más claras que el fondo, para seguir la fila con la vista
ROW_FILL: RGB = (17, 21, 30)
# Más de esto en una sola tarjeta y las filas quedan muy bajas para el celular:
# cogs/info.py reparte las tablas largas (Champions, 36 equipos) en varias tarjetas
MAX_ROWS = 20


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
    # Filas altas y letra grande: Discord encoge la imagen a ~400 px de ancho en el celular
    row_h = 58 if total_rows <= MAX_ROWS else 46
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
    label_font = font("text", 20, "SemiBold")
    middle = y + COLUMNS_H // 2
    draw.text((62, middle), "#", font=label_font, fill=MUTED, anchor="mm")
    draw.text((150, middle), "TEAM", font=label_font, fill=MUTED, anchor="lm")
    for label, x in STAT_X.items():
        draw.text((x, middle), label, font=label_font, fill=MUTED, anchor="mm")
    y += COLUMNS_H

    big = row_h > 46
    name_font = font("text", 30 if big else 25, "SemiBold")
    stat_font = font("text", 27 if big else 23, "Medium")
    pts_font = font("text", 31 if big else 26, "Bold")
    for group in groups:
        if group.title:
            draw.rectangle((24, y + 18, 30, y + GROUP_TITLE_H - 10), fill=BLUE)
            draw.text((42, y + GROUP_TITLE_H // 2 + 4), group.title.upper(),
                      font=font("title", 26, "SemiBold"), fill=TEXT, anchor="lm")  # fmt: skip
            y += GROUP_TITLE_H
        # Puestos repetidos (empate total): se marcan con "=" delante, como en la prensa
        positions = [r.position for r in group.rows]
        for i, row in enumerate(group.rows):
            tied = positions.count(row.position) > 1
            _table_row(canvas, draw, row, y, row_h, i % 2 == 0,
                       name_font, stat_font, pts_font, tied)  # fmt: skip
            y += row_h

    if legend_lines:
        y += 16
        for line in legend_lines:
            x = 30
            for color, label in line:
                draw.rectangle((x, y + 12, x + 18, y + 30), fill=color)
                draw.text((x + 26, y + 21), label, font=_legend_font(), fill=TEXT, anchor="lm")
                x += 26 + int(_legend_font().getlength(label)) + 22
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
    tied: bool = False,
) -> None:
    middle = y + row_h // 2
    base = ROW_FILL if even else BLACK
    if row.zone_color:
        # La fila de una zona lleva un toque de su color: se ve aunque la franja sea fina
        base = _mix(base, row.zone_color, 0.10)
    if even or row.zone_color:
        draw.rectangle((24, y, WIDTH - 24, y + row_h - 1), fill=base)
    if row.zone_color:
        # Franja a la izquierda: dice la zona (Champions, descenso...)
        draw.rectangle((24, y, 36, y + row_h - 1), fill=row.zone_color)
    # El puesto en blanco (en el color de la zona costaba leerlo); la franja ya dice la zona
    position_font = font("title", 29 if row_h > 46 else 25, "SemiBold")
    label = f"={row.position}" if tied else str(row.position)
    if tied:  # un carácter más: un poco más pequeño para que no se salga de la columna
        position_font = font("title", position_font.size - 4, "SemiBold")
    draw.text((66, middle), label, font=position_font, fill=TEXT, anchor="mm")
    # El escudo como sticker (borde claro con su forma): se ven también los oscuros
    side = row_h - 10
    tile(canvas, row.crest, (96, middle - side // 2, 96 + side, middle + side // 2))
    draw.text((152, middle), truncate(row.name, name_font, 340), font=name_font, fill=TEXT,
              anchor="lm")  # fmt: skip
    gd = f"{row.goal_difference:+d}".replace("-", MINUS) if row.goal_difference else "0"
    stats = {"P": row.played, "W-D-L": f"{row.won}-{row.draw}-{row.lost}", "GD": gd}
    for label, value in stats.items():
        draw.text((STAT_X[label], middle), str(value), font=stat_font, fill=STAT_COLOR,
                  anchor="mm")  # fmt: skip
    draw.text((STAT_X["PTS"], middle), str(row.points), font=pts_font, fill=TEXT, anchor="mm")


def _mix(a: RGB, b: RGB, amount: float) -> RGB:
    """Mezcla dos colores: `amount` 0 = solo a, 1 = solo b."""
    return (
        round(a[0] + (b[0] - a[0]) * amount),
        round(a[1] + (b[1] - a[1]) * amount),
        round(a[2] + (b[2] - a[2]) * amount),
    )


def _legend_font() -> ImageFont.FreeTypeFont:
    return font("text", 21, "Medium")


def _legend_lines(legend: Sequence[tuple[RGB, str]]) -> list[list[tuple[RGB, str]]]:
    """Reparte la leyenda en renglones que quepan en el ancho de la tarjeta."""
    lines: list[list[tuple[RGB, str]]] = []
    current: list[tuple[RGB, str]] = []
    used = 30
    for color, label in legend:
        size = 26 + int(_legend_font().getlength(label)) + 22
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
    """Perfil del equipo: escudo grande, datos, racha W/D/L y el próximo partido tipo "versus".

    Si no hay partidos (ligas que el plan gratis no cubre) la tarjeta es más baja y solo dice
    eso en una línea, en vez de dejar dos columnas vacías.
    """
    empty = not form and not next_match
    # Datos: etiqueta pequeña a la izquierda y valor a la derecha; si el valor es largo, sigue
    # en otra línea. Se mide antes de dibujar: la altura de la tarjeta depende de esto
    label_font = font("text", 21, "SemiBold")
    value_font = font("text", 26, "SemiBold")
    # La columna de valores empieza después de la etiqueta más larga ("COMPETITIONS")
    value_x = 332 + max((int(label_font.getlength(lb.upper())) for lb, _ in facts[:4]), default=0)
    value_x += 26
    rows = [(lb, _wrap(v, value_font, WIDTH - 40 - value_x)[:3]) for lb, v in facts[:4]]
    facts_bottom = 178 + sum(40 + (len(lines) - 1) * 32 for _, lines in rows)
    top = max(330, facts_bottom + 16)  # la línea que separa los datos de los partidos
    height = top + (140 if empty else 330)

    canvas = Image.new("RGBA", (WIDTH, height), (*BLACK, 255))
    # El logo del bot, grande y muy tenue, saliendo por la esquina de abajo a la derecha
    paste(canvas, logo(560, opacity=0.05), (WIDTH - 420, height - 330))
    draw = ImageDraw.Draw(canvas)

    tile(canvas, crest, (40, 40, 290, 290))

    brand(canvas, right=WIDTH - 28, top=26, size=96)
    title_font = fit_font(name.upper(), "title", "Bold", 66, 440, 30)
    draw.text((330, 80), name.upper(), font=title_font, fill=TEXT, anchor="lm")
    draw.text((332, 134), subtitle, font=font("text", 25, "Medium"), fill=MUTED, anchor="lm")

    y = 178
    for label, lines in rows:
        draw.text((332, y + 15), label.upper(), font=label_font, fill=MUTED, anchor="lm")
        for i, line in enumerate(lines):
            draw.text((value_x, y + 15 + i * 32), line, font=value_font, fill=TEXT, anchor="lm")
        y += 40 + (len(lines) - 1) * 32
    draw.rectangle((40, top, WIDTH - 40, top + 1), fill=LINE)

    if empty:
        draw.text((40, top + 58), "Match data isn't available for this club yet",
                  font=font("text", 25, "SemiBold"), fill=MUTED, anchor="lm")  # fmt: skip
        _footer(draw, height)
        return to_png(canvas)

    # Racha: cuadrados rectos (ganó azul, empató gris, perdió rojo apagado)
    y = top + 44
    draw.text((40, y), "FORM", font=font("title", 26, "SemiBold"), fill=MUTED, anchor="lm")
    if form:
        x = 40
        for result in form:
            draw.rectangle((x, y + 28, x + 56, y + 84), fill=FORM_COLORS.get(result, DRAW))
            draw.text((x + 28, y + 56), result, font=font("title", 30, "Bold"), fill=TEXT,
                      anchor="mm")  # fmt: skip
            x += 64
    else:
        draw.text((40, y + 56), "No recent matches", font=font("text", 24), fill=MUTED,
                  anchor="lm")  # fmt: skip
    if last_result:
        # "Santander 0-3 Real Madrid · Sun 01 Nov": el resultado arriba, la fecha abajo
        result, _, when = last_result.partition(" · ")
        result_font = font("text", 25, "SemiBold")
        draw.text((40, y + 124), truncate(result, result_font, 420), font=result_font,
                  fill=TEXT, anchor="lm")  # fmt: skip
        if when:
            draw.text((40, y + 158), f"Last match · {when}", font=font("text", 24),
                      fill=MUTED, anchor="lm")  # fmt: skip

    # Próximo partido estilo "versus": los dos escudos como stickers
    draw.text((500, y), "NEXT MATCH", font=font("title", 26, "SemiBold"), fill=MUTED,
              anchor="lm")  # fmt: skip
    if next_match:
        for crest_bytes, x in ((next_match.home_crest, 552), (next_match.away_crest, 806)):
            tile(canvas, crest_bytes, (x - 56, y + 18, x + 56, y + 130))
        draw.text((679, y + 74), "VS", font=font("title", 42, "Bold"), fill=BLUE, anchor="mm")
        where = "vs" if next_match.home else "at"
        line_font = font("text", 25, "SemiBold")
        draw.text((679, y + 158), truncate(f"{where} {next_match.opponent}", line_font, 380),
                  font=line_font, fill=TEXT, anchor="mm")  # fmt: skip
        detail_font = fit_font(f"{next_match.when} · {next_match.competition}", "text",
                               "Regular", 24, 390, 16)  # fmt: skip
        draw.text((679, y + 192), f"{next_match.when} · {next_match.competition}",
                  font=detail_font, fill=MUTED, anchor="mm")  # fmt: skip
    else:
        draw.text((500, y + 56), "No match scheduled", font=font("text", 24), fill=MUTED,
                  anchor="lm")  # fmt: skip

    _footer(draw, height)
    return to_png(canvas)


def _wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Parte el texto en líneas que quepan en `max_width` (por palabras)."""
    lines: list[str] = []
    for word in text.split():
        if lines and fnt.getlength(f"{lines[-1]} {word}") <= max_width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return [truncate(line, fnt, max_width) for line in lines] or [""]


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
    draw.text((WIDTH - 30, y), SOURCE, font=font("text", 17), fill=MUTED, anchor="rm")
