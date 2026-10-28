"""Lo que todo provider debe cumplir, más los errores que pueden lanzar.

- `FootballProvider` es un "Protocol": una lista de métodos que un cliente de API debe tener.
  Hoy solo lo implementa `football_data.py`. Sirve para que `services/football.py` no dependa
  de una API concreta, y para que los tests usen un provider falso (tests/test_football_service.py).
- Los errores de aquí los convierte en mensajes para el usuario `bot.py:on_app_command_error`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from footballbot.models import Competition, Match, Standing, Team


class ProviderError(Exception):
    """The data source failed or returned something unusable.

    Ejemplos: la API está caída, tardó demasiado o devolvió un error 500.
    """


class NotFoundError(ProviderError):
    """The requested resource does not exist (or not on our plan).

    Ejemplos: un id de equipo que no existe, o la tabla del Mundial fuera de temporada (404).
    """


class NotInPlanError(NotFoundError):
    """Existe, pero el plan gratis de la API no lo incluye (403). Ej.: las selecciones."""


class RateLimitedError(ProviderError):
    """Gastamos las peticiones permitidas por minuto y hay que esperar `retry_after` segundos."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Estado de la API que muestra `/ping`."""

    name: str
    last_latency_ms: float | None = None  # cuánto tardó la última petición real
    requests_left: int | None = None  # peticiones que quedan este minuto (según la API)


class FootballProvider(Protocol):
    """A source of live football data. Date ranges are inclusive on both ends.

    "Inclusive" quiere decir que `date_from` y `date_to` cuentan los dos: del 24 al 25
    trae los partidos del 24 y del 25. (La API de football-data lo hace distinto; el
    provider se encarga de convertirlo.)
    """

    async def competitions(self) -> list[Competition]: ...

    async def matches(
        self,
        date_from: date,
        date_to: date,
        *,
        competitions: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[Match]: ...

    async def team_matches(self, team_id: int, date_from: date, date_to: date) -> list[Match]: ...

    async def standings(self, competition: str) -> list[Standing]: ...

    async def team(self, team_id: int) -> Team: ...

    async def competition_teams(self, competition: str) -> list[Team]: ...

    def health(self) -> ProviderHealth: ...

    async def aclose(self) -> None: ...
