"""Client for https://www.football-data.org/ (v4). Free tier: 10 requests per minute.

Cliente de la API de football-data.org: partidos, tablas y equipos.

Quién lo usa: `bot.py` lo crea una vez y se lo pasa a `FootballService` (services/football.py).
Nadie más debería llamarlo directamente.

Cómo funciona cada petición (método `_get`):
1. ¿Ya la pedimos hace poco? -> se devuelve la copia guardada (caché), sin gastar cuota.
2. Si no, se espera turno en el `RateLimiter` (máximo 10 por minuto).
3. Se hace la petición HTTP con la key en el header `X-Auth-Token`.
4. Si la API dice 429 (demasiadas peticiones), se espera y se reintenta una vez.
5. El JSON se convierte en modelos (`_team`, `_match`, ...) al final de este archivo.

Para añadir un endpoint nuevo: copia un método como `team()`, elige un TTL de caché
y escribe (o reutiliza) la función que convierte el JSON en un modelo.
Docs de la API: https://docs.football-data.org/general/v4/index.html
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from cachetools import TTLCache

from footballbot.models import Competition, Match, Player, Standing, StandingRow, Team
from footballbot.providers.base import (
    NotFoundError,
    ProviderError,
    ProviderHealth,
    RateLimitedError,
)
from footballbot.providers.ratelimit import RateLimiter

log = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"

# Cache lifetimes in seconds
# Cuánto tiempo guardamos cada respuesta antes de volver a pedirla a la API.
TTL_LIVE = 30  # partidos en vivo: cambian rápido
TTL_MATCHES = 5 * 60  # partidos del día
TTL_STANDINGS = 10 * 60  # tablas
TTL_TEAMS = 24 * 60 * 60  # equipos y competiciones: casi nunca cambian

# On a 429, wait and retry once if the counter resets within this many seconds
MAX_RETRY_WAIT = 20

# Un objeto JSON ya convertido a diccionario de Python.
Json = dict[str, Any]


class FootballDataProvider:
    """Implementa `FootballProvider` (providers/base.py) para football-data.org."""

    name = "football-data.org"

    def __init__(
        self,
        api_key: str,
        *,
        requests_per_minute: int = 10,
        # Los tests pasan aquí un transport falso para no llamar a la API real.
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Un solo cliente HTTP para todo el bot: reutiliza conexiones y es más rápido.
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-Auth-Token": api_key},
            timeout=10,
            transport=transport,
        )
        self._limiter = RateLimiter(requests_per_minute, 60)
        # Una caché por cada TTL. La clave es (ruta, parámetros) de la petición.
        self._caches: dict[int, TTLCache[tuple[str, tuple[tuple[str, str], ...]], Json]] = {}
        # Datos para /ping
        self._last_latency_ms: float | None = None
        self._requests_left: int | None = None

    async def aclose(self) -> None:
        """Cierra las conexiones HTTP. Lo llama `bot.py:close()` al apagar el bot."""
        await self._client.aclose()

    def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self._last_latency_ms, self._requests_left)

    # --- endpoints -------------------------------------------------------------------------
    # Un método por cada endpoint de la API que usamos. Todos devuelven modelos.

    async def competitions(self) -> list[Competition]:
        """Las competiciones del plan gratis (13). GET /competitions"""
        data = await self._get("/competitions", ttl=TTL_TEAMS)
        return [_competition(c, c["area"]) for c in data["competitions"]]

    async def matches(
        self,
        date_from: date,
        date_to: date,
        *,
        competitions: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[Match]:
        """Partidos entre dos fechas UTC (incluidas). GET /matches

        `competitions`: códigos para filtrar, ej. ["PL"]. `status`: ej. "LIVE".
        """
        # The API's dateTo is exclusive; ours is inclusive.
        # Ej.: para traer solo el 25 hay que pedir dateFrom=25 y dateTo=26.
        params = {"dateFrom": date_from.isoformat(), "dateTo": _after(date_to)}
        if competitions:
            params["competitions"] = ",".join(competitions)
        if status:
            params["status"] = status
        ttl = TTL_LIVE if status == "LIVE" else TTL_MATCHES
        data = await self._get("/matches", params, ttl=ttl)
        return [_match(m) for m in data["matches"]]

    async def team_matches(self, team_id: int, date_from: date, date_to: date) -> list[Match]:
        """Partidos de un equipo entre dos fechas, ordenados. GET /teams/{id}/matches"""
        params = {"dateFrom": date_from.isoformat(), "dateTo": _after(date_to)}
        data = await self._get(f"/teams/{team_id}/matches", params, ttl=TTL_MATCHES)
        return [_match(m) for m in data["matches"]]

    async def standings(self, competition: str) -> list[Standing]:
        """Tablas de una competición. GET /competitions/{code}/standings

        La API devuelve tablas TOTAL, HOME (solo de local) y AWAY; nos quedamos con TOTAL.
        """
        data = await self._get(f"/competitions/{competition}/standings", ttl=TTL_STANDINGS)
        comp = _competition(data["competition"], data["area"])
        matchday = (data.get("season") or {}).get("currentMatchday")
        return [
            Standing(
                competition=comp,
                rows=tuple(_standing_row(r) for r in table["table"]),
                stage=table.get("stage"),
                group=table.get("group"),
                matchday=matchday,
            )
            for table in data["standings"]
            if table.get("type") == "TOTAL"
        ]

    async def team(self, team_id: int) -> Team:
        """Perfil completo de un equipo, con plantilla. GET /teams/{id}"""
        return _team(await self._get(f"/teams/{team_id}", ttl=TTL_TEAMS))

    async def competition_teams(self, competition: str) -> list[Team]:
        """Todos los equipos de una competición. GET /competitions/{code}/teams

        Lo usa el índice de equipos del autocompletado (services/football.py).
        """
        data = await self._get(f"/competitions/{competition}/teams", ttl=TTL_TEAMS)
        return [_team(t) for t in data["teams"]]

    # --- HTTP ------------------------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, str] | None = None, *, ttl: int) -> Json:
        """GET con caché, límite de peticiones, un reintento si hay 429 y manejo de errores."""
        # 1. Caché: si ya tenemos esta respuesta y no ha vencido, la devolvemos.
        key = (path, tuple(sorted((params or {}).items())))
        cache = self._caches.setdefault(ttl, TTLCache(maxsize=512, ttl=ttl))
        if key in cache:
            return cache[key]

        # 2 y 3. Petición real (espera turno en el rate limiter dentro de `_request`).
        response = await self._request(path, params)
        # 4. 429 = "demasiadas peticiones". La API dice en cuántos segundos se libera el cupo.
        if response.status_code == 429:
            wait = _reset_seconds(response)
            if wait > MAX_RETRY_WAIT:
                # Esperar tanto haría que el usuario vea el comando colgado: mejor avisarle.
                raise RateLimitedError(wait)
            log.info("football-data rate limited, retrying in %ss", wait)
            await asyncio.sleep(wait)
            response = await self._request(path, params)
            if response.status_code == 429:
                raise RateLimitedError(_reset_seconds(response))

        # Errores HTTP -> nuestros errores (ver providers/base.py).
        if response.status_code == 404:
            raise NotFoundError(f"{path} not found")
        if response.status_code == 403:
            raise NotFoundError(f"{path} is not included in the free plan")
        if response.is_error:
            raise ProviderError(f"football-data returned {response.status_code} for {path}")

        # 5. Guardamos en caché y devolvemos el JSON (se convierte a modelos en cada endpoint).
        data: Json = response.json()
        cache[key] = data
        return data

    async def _request(self, path: str, params: dict[str, str] | None) -> httpx.Response:
        """Una petición HTTP, respetando el rate limiter y anotando datos para /ping."""
        await self._limiter.acquire()
        started = time.perf_counter()
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as e:
            # Sin internet, timeout, DNS... -> ProviderError ("el servicio no responde").
            raise ProviderError(f"football-data request failed: {e!r}") from e
        self._last_latency_ms = (time.perf_counter() - started) * 1000
        # La API dice en este header cuántas peticiones nos quedan este minuto.
        left = response.headers.get("X-Requests-Available-Minute")
        if left is not None and left.isdigit():
            self._requests_left = int(left)
        return response


# --- parsing -------------------------------------------------------------------------------
# Funciones que convierten el JSON de la API en nuestros modelos (models/football.py).
# Si la API cambia un nombre de campo, solo hay que tocar aquí.


def _after(day: date) -> str:
    """El día siguiente en formato YYYY-MM-DD (para el `dateTo` exclusivo de la API)."""
    return (day + timedelta(days=1)).isoformat()


def _reset_seconds(response: httpx.Response) -> float:
    """Segundos hasta que la API reinicia el contador de peticiones (60 si no lo dice)."""
    value = response.headers.get("X-RequestCounter-Reset", "60")
    return float(value) if value.isdigit() else 60.0


def _competition(data: Json, area: Json | None = None) -> Competition:
    return Competition(
        code=data["code"],
        name=data["name"],
        area=(area or {}).get("name", ""),
        emblem=data.get("emblem") or None,
        type=data.get("type") or "LEAGUE",
    )


def _team(data: Json) -> Team:
    # Sirve tanto para el equipo "resumido" de un partido o tabla (id, nombre, escudo)
    # como para el perfil completo de /teams/{id}. Los campos que falten quedan en None.
    coach = data.get("coach") or {}
    # Knockout fixtures list undecided teams with null id and name
    # (ej. una final cuyos equipos aún no se conocen)
    name = data.get("name") or "TBD"
    return Team(
        id=data.get("id") or 0,
        name=name,
        short_name=data.get("shortName") or name,
        tla=data.get("tla") or None,
        crest=data.get("crest") or None,
        country=(data.get("area") or {}).get("name"),
        founded=data.get("founded"),
        venue=data.get("venue") or None,
        colors=data.get("clubColors") or None,
        website=data.get("website") or None,
        coach=coach.get("name") or None,
        competitions=tuple(_competition(c) for c in data.get("runningCompetitions") or ()),
        squad=tuple(_player(p) for p in data.get("squad") or ()),
    )


def _player(data: Json) -> Player:
    born = data.get("dateOfBirth")
    return Player(
        id=data["id"],
        name=data["name"],
        position=data.get("position"),
        nationality=data.get("nationality"),
        date_of_birth=date.fromisoformat(born) if born else None,
    )


def _match(data: Json) -> Match:
    # Durante el partido, `fullTime` ya trae el marcador actual.
    full_time = (data.get("score") or {}).get("fullTime") or {}
    return Match(
        id=data["id"],
        competition=_competition(data["competition"], data.get("area")),
        # "2026-10-25T14:00:00Z" -> datetime con zona UTC
        kickoff=datetime.fromisoformat(data["utcDate"]),
        status=data["status"],
        home=_team(data["homeTeam"]),
        away=_team(data["awayTeam"]),
        home_score=full_time.get("home"),
        away_score=full_time.get("away"),
        matchday=data.get("matchday"),
        stage=data.get("stage"),
        group=data.get("group"),
    )


def _standing_row(data: Json) -> StandingRow:
    return StandingRow(
        position=data["position"],
        team=_team(data["team"]),
        played=data["playedGames"],
        won=data["won"],
        draw=data["draw"],
        lost=data["lost"],
        goals_for=data["goalsFor"],
        goals_against=data["goalsAgainst"],
        goal_difference=data["goalDifference"],
        points=data["points"],
    )
