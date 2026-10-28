"""Facade over the football providers. Commands only talk to this, never to a provider.

`FootballService` es el "intermediario" entre los comandos y la API:
- Los cogs (cogs/info.py) le piden cosas en términos del bot: "los partidos de hoy",
  "el perfil de este equipo".
- Él decide qué pedirle al provider (providers/football_data.py), filtra y ordena el resultado.
- No sabe nada de Discord: por eso se puede probar sin Discord (tests/test_football_service.py).

También guarda el índice de equipos en memoria para el autocompletado de `/team`.

Quién lo crea: `bot.py` (`self.football`). Los cogs lo usan como `self.bot.football`.
"""

import asyncio
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from footballbot.errors import UserFacingError
from footballbot.models import Competition, Match, Standing, Team
from footballbot.providers.base import FootballProvider, ProviderError, ProviderHealth
from footballbot.services.leagues import CLUB_COMPETITIONS, league_order
from footballbot.services.text import normalize

log = logging.getLogger(__name__)

FORM_LENGTH = 5  # cuántos partidos muestra la racha de /team
FORM_DAYS_BACK = 60  # hasta cuántos días atrás buscamos esos partidos
NEXT_MATCH_DAYS_AHEAD = 30  # hasta cuántos días adelante buscamos el próximo partido
# Spacing between requests while building the team index, so commands still get quota
# (una petición cada 12 s = 5 por minuto para el índice; quedan otras 5 para los comandos)
INDEX_REQUEST_DELAY = 12.0


@dataclass(frozen=True, slots=True)
class MatchGroup:
    """Los partidos de una competición. /matches y /live muestran una sección por grupo."""

    competition: Competition
    matches: tuple[Match, ...]


@dataclass(frozen=True, slots=True)
class TeamProfile:
    """Todo lo que muestra `/team`."""

    team: Team
    recent: tuple[Match, ...]  # last finished matches, oldest first
    next_match: Match | None


class FootballService:
    def __init__(self, provider: FootballProvider, tz: ZoneInfo) -> None:
        self._provider = provider
        self._tz = tz  # zona horaria del bot (TIMEZONE en .env)
        # Índice de equipos para el autocompletado: id -> equipo,
        # e id -> nombres normalizados para buscar ("real madrid cf", "real madrid", "rma").
        self._teams: dict[int, Team] = {}
        self._team_keys: dict[int, tuple[str, ...]] = {}

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def today(self) -> date:
        """La fecha de hoy en la zona horaria del bot (no la de UTC)."""
        return datetime.now(self._tz).date()

    # --- matches ---------------------------------------------------------------------------

    async def matches_on(self, day: date, league: str | None = None) -> list[MatchGroup]:
        """Matches whose kick-off falls on `day` in the bot's time zone.

        La API trabaja en UTC. Un día en Bogotá (UTC-5) va de las 05:00 UTC de ese día a las
        04:59 UTC del día siguiente, así que pedimos los dos días UTC y luego filtramos.
        Ejemplo: un partido a las 20:00 del 24 en Bogotá es a la 01:00 UTC del 25.
        """
        start = datetime.combine(day, time.min, tzinfo=self._tz)  # 00:00 hora local
        end = start + timedelta(days=1)  # 00:00 del día siguiente, hora local
        matches = await self._provider.matches(
            start.astimezone(UTC).date(),
            (end - timedelta(microseconds=1)).astimezone(UTC).date(),
            competitions=[league] if league else None,
        )
        return group_by_competition(m for m in matches if start <= m.kickoff < end)

    async def live(self, league: str | None = None) -> list[MatchGroup]:
        """Partidos que se están jugando ahora.

        Ojo: en el plan gratis los datos llegan con unos minutos de retraso.
        """
        today = datetime.now(UTC).date()
        # From yesterday so a match that kicked off before midnight UTC still shows up
        matches = await self._provider.matches(
            today - timedelta(days=1),
            today,
            competitions=[league] if league else None,
            status="LIVE",
        )
        return group_by_competition(m for m in matches if m.is_live)

    async def standings(self, league: str) -> list[Standing]:
        """Tablas de una liga. Puede lanzar NotFoundError si no hay tabla (ej. Mundial)."""
        return await self._provider.standings(league)

    # --- teams -----------------------------------------------------------------------------

    async def team_profile(self, query: str) -> TeamProfile:
        """Perfil de un equipo + sus últimos 5 resultados + su próximo partido.

        `query` es lo que llega del comando: el id (si eligió una sugerencia) o texto libre.
        """
        team_id = self.resolve_team_id(query)
        if team_id is None:
            raise UserFacingError(
                f"I couldn't find a team called **{query}**. Pick one from the suggestions."
            )
        today = self.today()
        # gather: hace las dos peticiones al mismo tiempo en vez de una tras otra.
        team, matches = await asyncio.gather(
            self._provider.team(team_id),
            # Un solo rango de fechas (60 días atrás a 30 adelante) da la racha y el próximo.
            self._provider.team_matches(
                team_id,
                today - timedelta(days=FORM_DAYS_BACK),
                today + timedelta(days=NEXT_MATCH_DAYS_AHEAD),
            ),
        )
        matches = sorted(matches, key=lambda m: m.kickoff)
        finished = [m for m in matches if m.is_finished]
        upcoming = (m for m in matches if m.is_live or m.is_upcoming)
        return TeamProfile(
            team=team,
            recent=tuple(finished[-FORM_LENGTH:]),  # los 5 últimos terminados
            next_match=next(upcoming, None),  # el primero que no ha terminado, o None
        )

    @property
    def indexed_teams(self) -> int:
        """Cuántos equipos hay en el índice (se muestra en /ping)."""
        return len(self._teams)

    def add_teams(self, teams: Iterable[Team]) -> None:
        """Mete equipos al índice del autocompletado."""
        for team in teams:
            self._teams[team.id] = team
            names = (team.name, team.short_name, team.tla or "")
            self._team_keys[team.id] = tuple(normalize(n) for n in names if n)

    async def refresh_team_index(
        self,
        leagues: Sequence[str] = CLUB_COMPETITIONS,
        delay: float = INDEX_REQUEST_DELAY,
    ) -> None:
        """Loads every team of `leagues` into memory for autocomplete. Slow on purpose.

        ¿Por qué un índice en memoria? Discord exige responder el autocompletado en menos
        de 3 s, y no podemos gastar una petición a la API por cada letra que escribe alguien.
        Lo llama la tarea `refresh_teams` de cogs/info.py al arrancar y cada 24 h.
        Tarda unos 2 minutos (11 ligas x 12 s); mientras tanto pueden faltar sugerencias.
        Solo clubes: las selecciones (Mundial, Euro) no están en el plan gratis de la API.
        """
        for i, code in enumerate(leagues):
            if i:
                await asyncio.sleep(delay)
            try:
                self.add_teams(await self._provider.competition_teams(code))
            except ProviderError as e:
                # Si una liga falla seguimos con las demás: mejor un índice incompleto que ninguno.
                log.warning("Could not load teams for %s: %s", code, e)
        log.info("Team index ready: %d teams", self.indexed_teams)

    def search_teams(self, query: str, limit: int = 25) -> list[Team]:
        """Busca equipos en el índice. Los mejores resultados primero (ver `_match_rank`)."""
        q = normalize(query)
        if not q:
            return sorted(self._teams.values(), key=lambda t: t.name)[:limit]
        ranked = []
        for team_id, keys in self._team_keys.items():
            rank = _match_rank(q, keys)
            if rank is not None:
                team = self._teams[team_id]
                ranked.append((rank, team.name, team))
        # Ordena por calidad del match y, si empatan, alfabéticamente.
        ranked.sort(key=lambda r: (r[0], r[1]))
        return [team for _, _, team in ranked[:limit]]

    def resolve_team_id(self, value: str) -> int | None:
        """Autocomplete sends the team id; a user who ignores it sends free text.

        "86" -> 86. "barcelona" -> el id del mejor resultado de la búsqueda. Sin resultado -> None.
        """
        value = value.strip()
        if value.isdigit():
            return int(value)
        hits = self.search_teams(value, limit=1)
        return hits[0].id if hits else None

    # --- status ----------------------------------------------------------------------------

    async def api_status(self) -> ProviderHealth:
        """Comprueba que la API responde (lo usa /ping). La lista de competiciones está en
        caché 1 día, así que casi nunca gasta una petición."""
        await self._provider.competitions()
        return self._provider.health()


def group_by_competition(matches: Iterable[Match]) -> list[MatchGroup]:
    """Agrupa partidos por competición, en el orden de LEAGUES y cada grupo por hora."""
    groups: dict[str, list[Match]] = {}
    competitions: dict[str, Competition] = {}
    for match in matches:
        groups.setdefault(match.competition.code, []).append(match)
        competitions[match.competition.code] = match.competition
    return [
        MatchGroup(competitions[code], tuple(sorted(groups[code], key=lambda m: m.kickoff)))
        for code in sorted(groups, key=league_order)
    ]


def _match_rank(query: str, keys: tuple[str, ...]) -> int | None:
    """0 exact, 1 prefix, 2 word prefix, 3 substring, None no match.

    Con query "madrid": "real madrid" empieza una palabra con "madrid" (2);
    con query "real": "real madrid" empieza con "real" (1). Menor número = mejor.
    """
    if query in keys:
        return 0
    if any(key.startswith(query) for key in keys):
        return 1
    if any(word.startswith(query) for key in keys for word in key.split()):
        return 2
    if any(query in key for key in keys):
        return 3
    return None
