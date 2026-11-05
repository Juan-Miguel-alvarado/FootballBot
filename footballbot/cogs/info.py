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

import asyncio
import io
import logging
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from footballbot.bot import FootballBot
from footballbot.cogs.common import (
    COLOR,
    MAX_EMBED_CHARS,
    MAX_EMBEDS_PER_MESSAGE,
    command_mention,
    date_autocomplete,
    image_url,
    league_autocomplete,
    pack_fields,
    parse_day,
    parse_league,
    split_lines,
    team_autocomplete,
    timestamp,
)
from footballbot.errors import UserFacingError
from footballbot.imaging import cards
from footballbot.models import Match, MatchStatus, Standing
from footballbot.providers.base import NotFoundError, ProviderError
from footballbot.services.football import MatchGroup, TeamProfile
from footballbot.services.leagues import (
    LEAGUES,
    NONE,
    ZONE_RGB,
    League,
    Zone,
    get_league,
    zone_for,
)

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
# Barra gris de los embeds "no hay nada ahora" (/live vacío)
IDLE_COLOR = discord.Color.from_rgb(90, 99, 116)
# Raya de los marcadores ("2\u20131"): la tipográficamente correcta, más fina que un guion
DASH = "\u2013"
# Racha de /team en texto (solo si falla la tarjeta): ganó, empató, perdió.
_FORM_EMOJI = {"W": "🟩", "D": "🟨", "L": "🟥"}
# /standings: emoji de la fila de títulos de la tabla
HEADER_EMOJI = "⚽"


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
        await self._send_matches(interaction, day, chosen)

    async def _send_matches(
        self, interaction: discord.Interaction, day: date, chosen: League | None
    ) -> None:
        """Manda los partidos de `day` (y de `chosen`, si se eligió una liga) como followup.

        Lo usan /matches y los botones de día (DayView): el mensaje lleva botones para ir al
        día anterior y al siguiente, o al próximo día con partidos si este no tiene.
        """
        code = chosen.code if chosen else None
        groups = await self.football.matches_on(day, code)

        # Un solo mensaje con una sección por liga (se reparte si no cabe)
        # El título ya dice el día: el aviso de "no hay partidos" no lo repite
        title = f"{day:%A %d %B}"
        empty = "No matches this day."
        if chosen:
            title = f"{chosen.emoji} {chosen.name} · {day:%a %d %b}"
            empty = f"No {chosen.name} matches this day."
        hint = f"Try another day, or {command_mention(self.bot, 'leagues')} for the list."
        next_day = None
        if not groups:
            # Sin partidos ese día: se dice cuándo es el próximo (y hay un botón para verlo)
            try:
                nxt = await self.football.next_matchday(day, code)
            except ProviderError:
                nxt = None
            if nxt:
                next_day, count = nxt
                matches = "match" if count == 1 else "matches"
                hint = f"Next: **{next_day:%A %d %B}** ({count} {matches})."
        batches = _league_embeds(
            groups,
            self.football.tz,
            title=title,
            empty=f"**{empty}**\n{hint}",
            footer="Kick-off times are shown in your timezone",
            single=chosen is not None,
        )
        view = DayView(self, day, chosen, jump_to=next_day)
        for i, batch in enumerate(batches):
            last = i == len(batches) - 1
            await interaction.followup.send(embeds=batch, **({"view": view} if last else {}))

    # /live [league]
    @app_commands.command(description="Matches being played right now")
    @app_commands.describe(league="Only this league (default: all)")
    @app_commands.autocomplete(league=league_autocomplete)
    async def live(self, interaction: discord.Interaction, league: str | None = None) -> None:
        chosen = parse_league(league)
        await interaction.response.defer()
        groups = await self.football.live(chosen.code if chosen else None)
        empty = "**Nothing is being played right now.**"
        if not groups:
            empty += await self._next_kickoff(chosen.code if chosen else None)
            empty += "\n-# Live scores can lag a few minutes behind."

        batches = _league_embeds(
            groups,
            self.football.tz,
            title="🔴 Live now",
            empty=empty,
            idle_color=True,
            footer="Scores can lag a few minutes behind",
            single=chosen is not None,
        )
        view = None
        if not groups:
            view = DayView(self, self.football.today(), chosen, only_today=True)
        for i, batch in enumerate(batches):
            last = i == len(batches) - 1
            await interaction.followup.send(
                embeds=batch, **({"view": view} if last and view else {})
            )

    async def _next_kickoff(self, league: str | None) -> str:
        """Para /live sin partidos: "Next kick-off: Arsenal vs Chelsea at 15:00 (in 2 hours)"."""
        try:
            groups = await self.football.matches_on(self.football.today(), league)
        except ProviderError:
            groups = []
        upcoming = sorted(
            (m for g in groups for m in g.matches if m.is_upcoming), key=lambda m: m.kickoff
        )
        if not upcoming:
            return (
                f"\n-# No more matches today. {command_mention(self.bot, 'matches')} "
                "with `date:tomorrow` shows the next ones."
            )
        nxt = upcoming[0]
        return (
            f"\nNext kick-off: **{nxt.home.short_name} vs {nxt.away.short_name}** "
            f"at {timestamp(nxt.kickoff)} ({timestamp(nxt.kickoff, 'R')})"
        )

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
        # Primero la tarjeta en imagen (issue #10); si algo falla, la tabla en texto de siempre.
        # La imagen va suelta (sin embed): así Discord la muestra más grande. El texto solo
        # dice quién va primero; la tarjeta ya dice liga y jornada.
        pngs = await self._standings_image(chosen, tables)
        if pngs:
            content = _leader_line(tables[0]) if len(tables) == 1 else None
            # Tablas largas (Champions): una tarjeta por mensaje, para que no salgan chiquitas
            for i, png in enumerate(pngs):
                file = discord.File(io.BytesIO(png), filename=f"standings-{i + 1}.png")
                await interaction.followup.send(content if i == 0 else None, file=file)
            return

        embed = discord.Embed(color=COLOR)

        embed.title = f"{chosen.emoji} {chosen.name} · Standings"

        if thumbnail := image_url(competition.emblem):
            embed.set_thumbnail(url=thumbnail)
        legend = _zone_legend(chosen.code, tables)
        if len(tables) == 1:
            # Liga normal: quién va primero, la tabla y la leyenda de colores, en la descripción.
            parts = [_leader_line(tables[0]), _table_block(tables[0], chosen.code), legend]
            embed.description = "\n".join(p for p in parts if p)
            embeds = [embed]
        else:
            # Torneo con grupos: un campo por grupo y la leyenda al final.
            fields = [(_group_name(t.group), _table_block(t, chosen.code)) for t in tables]
            if legend:
                fields.append(("Zones", legend))
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
        # Primero la tarjeta en imagen (issue #10); si algo falla, el embed de texto de siempre
        png = await self._team_image(profile)
        if png is None:
            await interaction.followup.send(embed=_team_embed(profile, self.football.tz))
            return
        # Arriba, el próximo partido con la hora en la zona de cada uno (la tarjeta no puede);
        # debajo, un botón que abre la web del club
        content = None
        if nxt := profile.next_match:
            home = nxt.home.id == profile.team.id
            rival = (nxt.away if home else nxt.home).short_name
            content = (
                f"Next: **{'vs' if home else 'at'} {rival}** · "
                f"{timestamp(nxt.kickoff, 'f')} ({timestamp(nxt.kickoff, 'R')})"
            )
        file = discord.File(io.BytesIO(png), filename="team.png")
        website = profile.team.website
        if website and website.startswith("http"):
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Official website", url=website))
            await interaction.followup.send(content, file=file, view=view)
        else:
            await interaction.followup.send(content, file=file)

    # --- tarjetas en imagen ----------------------------------------------------------------

    async def _images(self, urls: list[str | None]) -> list[bytes | None]:
        """Baja varias imágenes a la vez (con caché en disco). None si alguna falla."""

        async def one(url: str | None) -> bytes | None:
            if not (url := image_url(url)):
                return None
            try:
                return await self.bot.images.get(url)
            except Exception:
                log.warning("Could not download %s", url)
                return None

        return list(await asyncio.gather(*(one(url) for url in urls)))

    async def _standings_image(self, league: League, tables: list[Standing]) -> list[bytes]:
        """La tabla como tarjetas PNG (una, o varias si es muy larga). [] si no se pudo."""
        try:
            urls = [tables[0].competition.emblem] + [r.team.crest for t in tables for r in t.rows]
            emblem, *crests = await self._images(urls)
            crest_iter = iter(crests)
            groups = []
            for table in tables:
                rows = []
                for r in table.rows:
                    zone = zone_for(league.code, r.position, len(table.rows))
                    rows.append(
                        cards.TableRow(
                            position=r.position,
                            name=r.team.short_name,
                            crest=next(crest_iter),
                            played=r.played,
                            won=r.won,
                            draw=r.draw,
                            lost=r.lost,
                            goal_difference=r.goal_difference,
                            points=r.points,
                            zone_color=ZONE_RGB[zone.emoji] if zone else None,
                        )
                    )
                title = _group_name(table.group) if len(tables) > 1 else None
                groups.append(cards.TableGroup(title, tuple(rows)))
            legend = [(ZONE_RGB[z.emoji], z.label) for z in _zones_present(league.code, tables)]
            subtitle = "Standings"
            if tables[0].matchday:
                subtitle += f" · Matchday {tables[0].matchday}"
            pages = _pages(groups)
            pngs = []
            for number, page in enumerate(pages, start=1):
                page_subtitle = subtitle
                page_legend = legend
                if len(pages) > 1:
                    first, last = page[0].rows[0].position, page[-1].rows[-1].position
                    page_subtitle += f" · Places {first}{DASH}{last} ({number}/{len(pages)})"
                    # En cada mitad, solo las zonas que aparecen en ella
                    colors = {r.zone_color for g in page for r in g.rows}
                    page_legend = [item for item in legend if item[0] in colors]
                pngs.append(
                    await asyncio.to_thread(
                        cards.standings_card,
                        title=league.name,
                        subtitle=page_subtitle,
                        emblem=emblem,
                        groups=page,
                        legend=page_legend,
                    )
                )
            return pngs
        except Exception:
            log.exception("Could not draw the standings card for %s", league.code)
            return []

    async def _team_image(self, profile: TeamProfile) -> bytes | None:
        """El perfil del equipo como tarjeta PNG, o None si no se pudo generar."""
        team = profile.team
        tz = self.football.tz
        try:
            nxt = profile.next_match
            crest, home_crest, away_crest = await self._images(
                [team.crest, nxt.home.crest if nxt else None, nxt.away.crest if nxt else None]
            )
            subtitle = " · ".join(
                p for p in (team.country, f"Founded {team.founded}" if team.founded else None) if p
            )
            facts = [
                (label, value)
                for label, value in (
                    ("Stadium", team.venue),
                    ("Coach", team.coach),
                    ("Plays in", ", ".join(
                        _competition_name(c.code, c.name) for c in team.competitions)),
                )
                if value
            ]  # fmt: skip
            form = [m.result_for(team.id) or "?" for m in profile.recent]
            last_result = None
            if profile.recent:
                last = profile.recent[-1]
                when = _short_date(last.kickoff.astimezone(tz).date())
                last_result = (
                    f"{last.home.short_name} {last.home_score}-{last.away_score} "
                    f"{last.away.short_name} · {when}"
                )
            next_match = None
            if nxt:
                home = nxt.home.id == team.id
                next_match = cards.NextMatch(
                    home_crest=home_crest,
                    away_crest=away_crest,
                    opponent=(nxt.away if home else nxt.home).short_name,
                    home=home,
                    # Solo el día: la hora exacta va en el mensaje, en la zona de cada uno
                    when=f"{nxt.kickoff.astimezone(tz):%a %d %b}",
                    competition=_competition_name(nxt.competition.code, nxt.competition.name),
                )
            return await asyncio.to_thread(
                cards.team_card,
                name=team.short_name,
                subtitle=subtitle,
                crest=crest,
                facts=facts,
                form=form,
                last_result=last_result,
                next_match=next_match,
            )
        except Exception:
            log.exception("Could not draw the team card for %s", team.id)
            return None

    # /leagues
    @app_commands.command(description="Leagues and their codes")
    async def leagues(self, interaction: discord.Interaction) -> None:
        # No llama a la API (la lista es fija, services/leagues.py), así que responde directo
        # con send_message, sin defer.
        embed = discord.Embed(
            title=f"{len(LEAGUES)} competitions",
            description="Use the code or the name in any `league` option, "
            "like `/standings league:PL`.",
            color=COLOR,
        )
        for region, leagues in _leagues_by_region():
            lines = [f"{lg.emoji} `{lg.code}` {lg.name}" for lg in leagues]
            embed.add_field(name=region, value="\n".join(lines), inline=False)
        embed.set_footer(text="Data: football-data.org")
        await interaction.response.send_message(embed=embed)


class DayView(discord.ui.View):
    """Botones debajo de /matches: día anterior y siguiente (o el próximo día con partidos).

    Cada botón manda un mensaje nuevo con los partidos de ese día, como si se escribiera
    /matches con esa fecha. `only_today`: un solo botón "Today's matches" (para /live vacío).
    """

    def __init__(
        self,
        cog: Info,
        day: date,
        league: League | None,
        *,
        jump_to: date | None = None,
        only_today: bool = False,
    ) -> None:
        super().__init__(timeout=900)  # 15 minutos; después los botones dejan de responder
        self.cog = cog
        self.league = league
        if only_today:
            self._add("Today's matches", day, discord.ButtonStyle.primary)
            return
        self._add(f"Previous day · {day - timedelta(days=1):%a %d}", day - timedelta(days=1))
        if jump_to:
            self._add(f"Show {jump_to:%a %d %b}", jump_to, discord.ButtonStyle.primary)
        self._add(f"Next day · {day + timedelta(days=1):%a %d}", day + timedelta(days=1))

    def _add(
        self, label: str, day: date, style: discord.ButtonStyle = discord.ButtonStyle.secondary
    ) -> None:
        button: discord.ui.Button[DayView] = discord.ui.Button(label=label, style=style)

        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            await self.cog._send_matches(interaction, day, self.league)

        button.callback = callback
        self.add_item(button)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        # Los botones no pasan por bot.py: se responde aquí, con el mismo estilo de error
        await self.cog.bot._reply_error(
            interaction, "Couldn't load those matches. Try again in a moment."
        )
        log.warning("Day button failed: %s", error)


# --- formatting --------------------------------------------------------------------------------
# Funciones que convierten modelos en texto para los embeds. Si quieres cambiar cómo se ve
# un comando, es aquí.


def _match_line(match: Match, tz: ZoneInfo) -> str:
    """Una línea por partido.

    "<t:...:t> · Arsenal vs Chelsea" (por jugar; Discord muestra la hora local),
    "FT · **Arsenal** 2\u20131 Chelsea" (terminado, el ganador en negrita),
    "🔴 **LIVE** · Arsenal **1\u20130** Chelsea" (en vivo).
    """
    home, away = match.home.short_name, match.away.short_name
    has_score = match.home_score is not None and match.away_score is not None
    if match.is_upcoming or not has_score:
        # Por jugar: la hora como timestamp de Discord, que cada uno ve en su zona horaria
        # (o PST/CAN si se aplazó o canceló)
        when = _STATUS_LABELS.get(match.status) or f"**{timestamp(match.kickoff)}**"
        return f"{when} · {home} vs {away}"
    label = _STATUS_LABELS.get(match.status, match.status[:4])
    hs, as_ = match.home_score, match.away_score
    if match.is_live:
        return f"🔴 **{label}** · {home} **{hs}{DASH}{as_}** {away}"
    if match.is_finished:
        if hs > as_:
            home = f"**{home}**"
        elif as_ > hs:
            away = f"**{away}**"
    return f"{label} · {home} {hs}{DASH}{as_} {away}"


def _league_embeds(
    groups: list[MatchGroup],
    tz: ZoneInfo,
    *,
    title: str,
    empty: str,
    footer: str,
    single: bool = False,
    idle_color: bool = False,
) -> list[list[discord.Embed]]:
    """/matches y /live: un mensaje compacto con una sección (campo) por liga.

    Arriba el total ("16 matches · 3 competitions"); cada liga es un campo con su bandera.
    `single`: se pidió una sola liga; su logo va en la esquina y no hace falta el nombre en
    cada campo. Si no cabe en un embed (25 campos, 6000 caracteres) se reparte en varios, y
    devuelve "tandas": cada tanda es un mensaje.
    """
    total = sum(len(g.matches) for g in groups)
    header = discord.Embed(title=title, color=COLOR)
    if groups:
        matches = "match" if total == 1 else "matches"
        header.description = f"**{total}** {matches}"
        if not single:
            competitions = "competition" if len(groups) == 1 else "competitions"
            header.description += f" · {len(groups)} {competitions}"
        if single and (emblem := image_url(groups[0].competition.emblem)):
            header.set_thumbnail(url=emblem)
    else:
        header.description = empty
        if idle_color:
            header.color = IDLE_COLOR  # /live sin partidos: barra gris, no la del logo

    fields = []
    for group in groups:
        league = get_league(group.competition.code)
        name = f"{league.emoji} {league.name}" if league else group.competition.name
        lines = [_match_line(m, tz) for m in group.matches]
        # Si una liga no cabe en un campo (1024 caracteres), sigue en otro "(cont.)"
        for i, chunk in enumerate(split_lines(lines)):
            label = "Fixtures" if single else name
            fields.append((label if i == 0 else f"{label} (cont.)", chunk))
    embeds = pack_fields(header, fields)
    if groups:  # sin partidos, el pie (zona horaria, retraso) no aporta nada
        embeds[-1].set_footer(text=footer)

    # Discord deja 6000 caracteres por mensaje sumando todos sus embeds
    batches: list[list[discord.Embed]] = [[]]
    used = 0
    for embed in embeds:
        size = len(embed)
        if batches[-1] and (
            len(batches[-1]) >= MAX_EMBEDS_PER_MESSAGE or used + size > MAX_EMBED_CHARS
        ):
            batches.append([])
            used = 0
        batches[-1].append(embed)
        used += size
    return batches


def _pages(groups: list[cards.TableGroup], size: int = 18) -> list[list[cards.TableGroup]]:
    """Reparte una tabla muy larga (Champions: 36) en tarjetas de `size` filas.

    Las tablas normales (hasta cards.MAX_ROWS filas) y los torneos con grupos van en una sola.
    """
    if len(groups) != 1 or len(groups[0].rows) <= cards.MAX_ROWS:
        return [groups]
    rows = groups[0].rows
    return [
        [cards.TableGroup(groups[0].title, rows[i : i + size])] for i in range(0, len(rows), size)
    ]


def _leagues_by_region() -> list[tuple[str, list[League]]]:
    """/leagues: las ligas en tres grupos, en el orden de LEAGUES."""
    regions: dict[str, list[League]] = {
        "Europe": [],
        "South America": [],
        "International": [],
    }
    for league in LEAGUES:
        if league.code in ("CL", "WC", "EC"):
            regions["International"].append(league)
        elif league.area in ("Brazil", "South America"):
            regions["South America"].append(league)
        else:
            regions["Europe"].append(league)
    return [(name, leagues) for name, leagues in regions.items() if leagues]


def _table_block(table: Standing, code: str) -> str:
    """La tabla como bloque de código, para que las columnas queden alineadas.

    Cada fila empieza con el círculo de color de su zona (🔵 Champions, 🔴 descenso...; ver
    ZONES en services/leagues.py). Todas las filas empiezan con un emoji para que las columnas
    sigan alineadas. Los números como `:>2` significan "alinear a la derecha en 2 caracteres".
    Cabe en unos 40 caracteres de ancho para que se vea bien en el celular.
    """
    size = len(table.rows)
    header = (
        f"{HEADER_EMOJI} {'#':>2} {'Team':<14} {'P':>2} {'W':>2} {'D':>2} {'L':>2} "
        f"{'GD':>3} {'Pts':>3}"
    )
    rows = []
    for r in table.rows:
        zone = zone_for(code, r.position, size)
        # Diferencia de goles con signo (+7, -3), pero "0" en vez de "+0".
        gd = f"{r.goal_difference:+d}" if r.goal_difference else "0"
        rows.append(
            f"{zone.emoji if zone else NONE} {r.position:>2} {r.team.short_name[:14]:<14} "
            f"{r.played:>2} {r.won:>2} {r.draw:>2} {r.lost:>2} {gd:>3} {r.points:>3}"
        )
    return "```\n" + "\n".join([header, *rows]) + "\n```"


def _leader_line(table: Standing) -> str:
    """ "Leader: **Man City** · 21 pts, level on points with Arsenal" o "... 3 points clear"."""
    if not table.rows:
        return ""
    first = table.rows[0]
    line = f"Leader: **{first.team.short_name}** · {first.points} pts"
    if len(table.rows) > 1:
        second = table.rows[1]
        gap = first.points - second.points
        if gap:
            line += f", {gap} {'point' if gap == 1 else 'points'} clear of {second.team.short_name}"
        else:
            line += f", level on points with {second.team.short_name}"
    return line


def _zones_present(code: str, tables: list[Standing]) -> list[Zone]:
    """Las zonas que aparecen en estas tablas, sin repetir y en orden."""
    seen: dict[str, Zone] = {}
    for table in tables:
        for r in table.rows:
            if zone := zone_for(code, r.position, len(table.rows)):
                seen.setdefault(zone.label, zone)
    return list(seen.values())


def _zone_legend(code: str, tables: list[Standing]) -> str:
    """ "🔵 Champions League · 🟠 Europa League · 🔴 Relegation": solo las zonas que aparecen."""
    return " · ".join(f"{z.emoji} {z.label}" for z in _zones_present(code, tables))


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
