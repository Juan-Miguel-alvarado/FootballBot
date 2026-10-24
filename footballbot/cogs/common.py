"""Helpers shared by the cogs: autocomplete, argument parsing and embed building.

Herramientas que usan los comandos (cogs/info.py y cogs/admin.py):
- Autocompletado: las sugerencias que Discord muestra mientras escribes una opción.
- Parseo de argumentos: convertir lo que escribió el usuario ("tomorrow", "premier") en datos.
- Embeds: repartir el contenido en varios mensajes si no cabe (Discord tiene límites).

Para usar un autocompletado en un comando nuevo:
    @app_commands.autocomplete(league=league_autocomplete)
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from footballbot.errors import UserFacingError
from footballbot.services.leagues import League, find_league, search_leagues

# Solo para los type hints: importar bot.py aquí de verdad crearía un import circular.
if TYPE_CHECKING:
    from footballbot.bot import FootballBot

# Color de la barra lateral de los embeds (verde)
COLOR = discord.Color.from_rgb(46, 160, 67)

# Discord limits
MAX_CHOICES = 25  # sugerencias de autocompletado
MAX_FIELD_VALUE = 1024  # caracteres por campo de un embed
MAX_EMBED_CHARS = 5500  # real limit is 6000, keep room for title and footer
MAX_FIELDS = 25  # campos por embed
MAX_EMBEDS_PER_MESSAGE = 10

# Palabras aceptadas en la opción `date` de /matches y cuántos días suman a hoy.
_DAY_WORDS = {"today": 0, "tomorrow": 1, "yesterday": -1}


# --- autocomplete ----------------------------------------------------------------------------
# Discord llama estas funciones cada vez que el usuario escribe en una opción.
# `current` es lo que lleva escrito. Hay que responder en menos de 3 s, por eso
# ninguna llama a la API: todas leen datos que ya están en memoria.
# Cada Choice tiene `name` (lo que ve el usuario) y `value` (lo que recibe el comando).


async def league_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Sugiere ligas. El comando recibe el código: "PL"."""
    return [
        app_commands.Choice(name=f"{league.name} ({league.code})", value=league.code)
        for league in search_leagues(current)[:MAX_CHOICES]
    ]


async def team_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Sugiere equipos del índice en memoria. El comando recibe el id como texto: "86"."""
    bot: FootballBot = interaction.client  # type: ignore[assignment]
    return [
        app_commands.Choice(name=team.name[:100], value=str(team.id))
        for team in bot.football.search_teams(current, limit=MAX_CHOICES)
    ]


async def date_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Sugiere today/tomorrow/yesterday y los días de 3 atrás a 7 adelante."""
    bot: FootballBot = interaction.client  # type: ignore[assignment]
    today = bot.football.today()
    choices = [app_commands.Choice(name=f"{word.title()}", value=word) for word in _DAY_WORDS]
    for offset in range(-3, 8):
        day = today + timedelta(days=offset)
        # Se muestra "Sat 24 Oct 2026" pero el comando recibe "2026-10-24".
        choices.append(app_commands.Choice(name=day.strftime("%a %d %b %Y"), value=day.isoformat()))
    current = current.strip().lower()
    return [c for c in choices if current in c.name.lower() or current in c.value][:MAX_CHOICES]


# --- argument parsing ------------------------------------------------------------------------
# Convierten el texto de una opción en datos. Si el texto no sirve, lanzan UserFacingError
# y bot.py le muestra el mensaje al usuario.


def parse_day(value: str | None, today: date) -> date:
    """Accepts empty (today), today/tomorrow/yesterday or YYYY-MM-DD."""
    if not value or not value.strip():
        return today
    value = value.strip().lower()
    if value in _DAY_WORDS:
        return today + timedelta(days=_DAY_WORDS[value])
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UserFacingError(
            f"**{value}** is not a date. Use `today`, `tomorrow`, `yesterday` or `YYYY-MM-DD`."
        ) from None


def parse_league(value: str | None) -> League | None:
    """Liga a partir del código o del nombre escrito. None si la opción venía vacía."""
    if value is None:
        return None
    league = find_league(value)
    if league is None:
        raise UserFacingError(f"Unknown league **{value}**. See `/leagues` for the list.")
    return league


# --- embeds ----------------------------------------------------------------------------------
# Un embed es el "recuadro" con título, campos e imagen que muestra Discord.


def image_url(url: str | None) -> str | None:
    """Discord does not render SVG. football-data serves a PNG next to every SVG crest."""
    if not url:
        return None
    return url.removesuffix(".svg") + ".png" if url.endswith(".svg") else url


def split_lines(lines: list[str], limit: int = MAX_FIELD_VALUE) -> list[str]:
    """Joins lines into chunks of at most `limit` characters without breaking a line.

    Si una liga tiene tantos partidos que no caben en un campo (1024 caracteres), se parte
    en varios campos.
    """
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def pack_fields(
    base: discord.Embed, fields: list[tuple[str, str]], *, max_chars: int = MAX_EMBED_CHARS
) -> list[discord.Embed]:
    """Spreads fields over as many embeds as needed; only the first keeps the title.

    Un embed admite máximo 6000 caracteres y 25 campos. Un sábado con 13 ligas puede
    pasarse, así que repartimos los campos en varios embeds (hasta 10 por mensaje).
    `fields` es una lista de (título del campo, texto del campo).
    """
    embeds = [base]
    used = len(base.title or "") + len(base.description or "")
    for name, value in fields:
        size = len(name) + len(value)
        current = embeds[-1]
        if used + size > max_chars or len(current.fields) >= MAX_FIELDS:
            # Este campo ya no cabe: empezamos un embed nuevo.
            current = discord.Embed(color=base.color)
            embeds.append(current)
            used = 0
        current.add_field(name=name, value=value, inline=False)
        used += size
    return embeds[:MAX_EMBEDS_PER_MESSAGE]
