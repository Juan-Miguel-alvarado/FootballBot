"""Comandos de información de fútbol: /matches, /live, /standings, /team y /leagues.

Todos siguen el mismo patrón:
1. Leer y validar las opciones (parse_day, parse_league de cogs/common.py).
2. `await interaction.response.defer()`: Discord da solo 3 s para responder; defer muestra
   "FootballTrivia is thinking..." y nos da hasta 15 minutos.
3. Pedir los datos a `self.football` (services/football.py). Nunca directo a la API.
4. Armar el embed con las funciones de formato del final de este archivo.
5. Enviarlo con `interaction.followup.send(...)`.
Si algo falla en cualquier paso, bot.py:on_app_command_error le responde al usuario.

Para añadir un comando: copia `leagues` (el más simple) o `standings` (si llama a la API),
y añádelo a COMMANDS.md.
"""

import logging
from datetime import date
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from footballbot.bot import FootballBot
from footballbot.cogs.common import (
    COLOR,
    date_autocomplete,
    image_url,
    league_autocomplete,
    pack_fields,
    parse_day,
    parse_league,
    split_lines,
    team_autocomplete,
)
from footballbot.errors import UserFacingError
from footballbot.models import Match, MatchStatus, Standing
from footballbot.providers.base import NotFoundError
from footballbot.services.football import MatchGroup, TeamProfile
from footballbot.services.leagues import LEAGUES, get_league

log = logging.getLogger(__name__)

# Etiqueta corta que se muestra a la izquierda de cada partido según su estado.
_STATUS_LABELS = {
    MatchStatus.FINISHED: "FT",
    MatchStatus.AWARDED: "FT",
    MatchStatus.IN_PLAY: "LIVE",
    MatchStatus.PAUSED: "HT",
    MatchStatus.EXTRA_TIME: "ET",
    MatchStatus.PENALTY_SHOOTOUT: "PEN",
    MatchStatus.POSTPONED: "PST",
    MatchStatus.SUSPENDED: "SUS",
    MatchStatus.CANCELLED: "CAN",
}
# Racha de /team: ganó, empató, perdió.
_FORM_EMOJI = {"W": "🟩", "D": "🟨", "L": "🟥"}


class Info(commands.Cog):
    """Live football information from football-data.org."""

    def __init__(self, bot: FootballBot) -> None:
        self.bot = bot
        self.football = bot.football  # atajo: services/football.py

    # cog_load / cog_unload: discord.py los llama al cargar y descargar este cog.
    # Aquí arrancan y paran la tarea que llena el índice de equipos del autocompletado.
    async def cog_load(self) -> None:
        self.refresh_teams.start()

    async def cog_unload(self) -> None:
        self.refresh_teams.cancel()

    # Tarea en segundo plano: corre al arrancar y luego cada 24 horas.
    @tasks.loop(hours=24)
    async def refresh_teams(self) -> None:
        await self.football.refresh_team_index()

    # /matches [league] [date]
    @app_commands.command(description="Matches for a day, grouped by league")
    # En Python el parámetro se llama `when` (porque `date` ya es un tipo importado arriba),
    # pero en Discord el usuario lo ve como "date".
    @app_commands.rename(when="date")
    @app_commands.describe(
        league="Only this league (default: all)",
        when="today, tomorrow, yesterday or YYYY-MM-DD (default: today)",
    )
    @app_commands.autocomplete(league=league_autocomplete, when=date_autocomplete)
    async def matches(
        self, interaction: discord.Interaction, league: str | None = None, when: str | None = None
    ) -> None:
        # Se valida antes del defer: así un error de escritura sale rápido y solo para el usuario.
        day = parse_day(when, self.football.today())
        chosen = parse_league(league)
        await interaction.response.defer()
        groups = await self.football.matches_on(day, chosen.code if chosen else None)

        embed = discord.Embed(title=f"Matches · {day:%A %d %B %Y}", color=COLOR)
        if chosen:
            # Con una sola liga: su nombre en el título y su logo en la esquina.
            embed.title = f"{chosen.emoji} {chosen.name} · {day:%A %d %B}"
            if groups and (emblem := image_url(groups[0].competition.emblem)):
                embed.set_thumbnail(url=emblem)
        if not groups:
            embed.description = "No matches on this day."
        # Una sección (campo) por liga, repartidas en varios embeds si no caben en uno.
        embeds = pack_fields(embed, _match_fields(groups, self.football.tz, single=bool(chosen)))
        embeds[-1].set_footer(text=f"Kick-off times in {self.football.tz.key}")
        await interaction.followup.send(embeds=embeds)

    # /live [league]
    @app_commands.command(description="Matches being played right now")
    @app_commands.describe(league="Only this league (default: all)")
    @app_commands.autocomplete(league=league_autocomplete)
    async def live(self, interaction: discord.Interaction, league: str | None = None) -> None:
        chosen = parse_league(league)
        await interaction.response.defer()
        groups = await self.football.live(chosen.code if chosen else None)

        embed = discord.Embed(title="🔴 Live now", color=discord.Color.red())
        if not groups:
            embed.description = "No matches in progress right now. Try `/matches`."
        embeds = pack_fields(embed, _match_fields(groups, self.football.tz, single=bool(chosen)))
        embeds[-1].set_footer(text="Free data is delayed a few minutes")
        await interaction.followup.send(embeds=embeds)

    # /standings <league>
    @app_commands.command(description="League table")
    @app_commands.describe(league="League code or name")
    @app_commands.autocomplete(league=league_autocomplete)
    async def standings(self, interaction: discord.Interaction, league: str) -> None:
        chosen = parse_league(league)
        # `league` es obligatorio, así que parse_league nunca devuelve None aquí.
        assert chosen is not None
        await interaction.response.defer()
        try:
            tables = await self.football.standings(chosen.code)
        except NotFoundError:
            # Ej. el Mundial entre ediciones: la API responde 404.
            tables = []
        if not tables:
            raise UserFacingError(
                f"There is no table for **{chosen.name}** right now. "
                "Tournaments only have one during their group stage."
            )

        competition = tables[0].competition
        embed = discord.Embed(title=f"{chosen.emoji} {chosen.name} · standings", color=COLOR)
        if thumbnail := image_url(competition.emblem):
            embed.set_thumbnail(url=thumbnail)
        if len(tables) == 1:
            # Liga normal: una sola tabla en la descripción del embed.
            embed.description = _table_block(tables[0])
            embeds = [embed]
        else:
            # Torneo con grupos: un campo por grupo.
            fields = [(_group_name(t.group), _table_block(t)) for t in tables]
            embeds = pack_fields(embed, fields)
        if tables[0].matchday:
            embeds[-1].set_footer(text=f"Matchday {tables[0].matchday}")
        await interaction.followup.send(embeds=embeds)

    # /team <team>
    @app_commands.command(description="Team profile: crest, stadium, coach and recent form")
    @app_commands.describe(team="Team name")
    @app_commands.autocomplete(team=team_autocomplete)
    async def team(self, interaction: discord.Interaction, team: str) -> None:
        # `team` trae el id si eligió una sugerencia ("86") o el texto si lo escribió a mano.
        await interaction.response.defer()
        profile = await self.football.team_profile(team)
        await interaction.followup.send(embed=_team_embed(profile, self.football.tz))

    # /leagues
    @app_commands.command(description="Leagues and competitions the bot knows, with their codes")
    async def leagues(self, interaction: discord.Interaction) -> None:
        # No llama a la API (la lista es fija, services/leagues.py), así que responde directo
        # con send_message, sin defer.
        lines = [f"{lg.emoji} `{lg.code:<3}` **{lg.name}** · {lg.area}" for lg in LEAGUES]
        embed = discord.Embed(title="Available leagues", description="\n".join(lines), color=COLOR)
        embed.set_footer(text="Use the code or the name in any league option")
        await interaction.response.send_message(embed=embed)


# --- formatting --------------------------------------------------------------------------------
# Funciones que convierten modelos en texto para los embeds. Si quieres cambiar cómo se ve
# un comando, es aquí.


def _match_line(match: Match, tz: ZoneInfo) -> str:
    """Una línea por partido.

    "`15:00` Arsenal vs Chelsea" (por jugar), "`   FT` Arsenal **2-1** Chelsea" (terminado),
    "`🔴LIVE` Arsenal **1-0** Chelsea" (en vivo).
    """
    home, away = match.home.short_name, match.away.short_name
    has_score = match.home_score is not None and match.away_score is not None
    if match.is_upcoming or not has_score:
        # Por jugar: la hora local (o PST/CAN si se aplazó o canceló).
        label = _STATUS_LABELS.get(match.status) or f"{match.kickoff.astimezone(tz):%H:%M}"
        return f"`{label:>5}` {home} vs {away}"
    label = _STATUS_LABELS.get(match.status, match.status[:4])
    if match.is_live:
        label = f"🔴{label}"
    return f"`{label:>5}` {home} **{match.home_score}-{match.away_score}** {away}"


def _match_fields(groups: list[MatchGroup], tz: ZoneInfo, *, single: bool) -> list[tuple[str, str]]:
    """Un campo (título, texto) por liga. `single`: se pidió una sola liga, el título ya la dice."""
    fields = []
    for group in groups:
        league = get_league(group.competition.code)
        name = f"{league.emoji} {league.name}" if league else group.competition.name
        if single:
            name = "Matches"
        lines = [_match_line(m, tz) for m in group.matches]
        # Si no cabe en un campo de 1024 caracteres, sigue en otro "(cont.)".
        for i, chunk in enumerate(split_lines(lines)):
            fields.append((name if i == 0 else f"{name} (cont.)", chunk))
    return fields


def _table_block(table: Standing) -> str:
    """La tabla como bloque de código, para que las columnas queden alineadas.

    Los números como `:>2` significan "alinear a la derecha en 2 caracteres".
    Cabe en unos 38 caracteres de ancho para que se vea bien en el celular.
    """
    header = f"{'#':>2} {'Team':<14} {'P':>2} {'W':>2} {'D':>2} {'L':>2} {'GD':>3} {'Pts':>3}"
    rows = [
        f"{r.position:>2} {r.team.short_name[:14]:<14} {r.played:>2} {r.won:>2} {r.draw:>2} "
        # Diferencia de goles con signo (+7, -3), pero "0" en vez de "+0".
        f"{r.lost:>2} {f'{r.goal_difference:+d}' if r.goal_difference else '0':>3} {r.points:>3}"
        for r in table.rows
    ]
    return "```\n" + "\n".join([header, *rows]) + "\n```"


def _group_name(group: str | None) -> str:
    """ "GROUP_A" -> "Group A"."""
    if not group:
        return "Table"
    return group.replace("_", " ").title()


def _short_date(day: date) -> str:
    """ "Wed 21 Oct"."""
    return f"{day:%a %d %b}"


def _team_embed(profile: TeamProfile, tz: ZoneInfo) -> discord.Embed:
    """El embed de /team: datos del club, racha, último y próximo partido."""
    team = profile.team
    embed = discord.Embed(title=team.name, color=COLOR)
    if team.website and team.website.startswith("http"):
        embed.url = team.website  # el título se vuelve un link a la web del club
    if crest := image_url(team.crest):
        embed.set_thumbnail(url=crest)

    # Solo se muestran los datos que la API trae (algunos clubes no tienen todos).
    details = [
        ("Country", team.country),
        ("Founded", str(team.founded) if team.founded else None),
        ("Stadium", team.venue),
        ("Coach", team.coach),
        ("Colors", team.colors),
    ]
    for name, value in details:
        if value:
            embed.add_field(name=name, value=value)
    if team.competitions:
        names = ", ".join(_competition_name(c.code, c.name) for c in team.competitions)
        embed.add_field(name="Competitions", value=names, inline=False)

    if profile.recent:
        # ⬜ si un resultado no se pudo calcular (no debería pasar con partidos terminados).
        form = " ".join(_FORM_EMOJI.get(m.result_for(team.id) or "", "⬜") for m in profile.recent)
        last = profile.recent[-1]
        when = _short_date(last.kickoff.astimezone(tz).date())
        embed.add_field(name=f"Form (last {len(profile.recent)})", value=form, inline=False)
        embed.add_field(
            name="Last match",
            value=f"{last.home.short_name} **{last.home_score}-{last.away_score}** "
            f"{last.away.short_name} · {when}",
            inline=False,
        )
    if nxt := profile.next_match:
        # "vs Barcelona" si juega de local, "at Barcelona" si juega de visitante.
        opponent = nxt.away if nxt.home.id == team.id else nxt.home
        where = "vs" if nxt.home.id == team.id else "at"
        kickoff = nxt.kickoff.astimezone(tz)
        comp = _competition_name(nxt.competition.code, nxt.competition.name)
        embed.add_field(
            name="Next match",
            value=f"{where} {opponent.short_name} · {kickoff:%a %d %b %H:%M} · {comp}",
            inline=False,
        )
    return embed


def _competition_name(code: str, fallback: str) -> str:
    """Nuestro nombre de la liga ("La Liga") en vez del de la API ("Primera Division")."""
    league = get_league(code)
    return league.name if league else fallback


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Info(bot))
