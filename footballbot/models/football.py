"""Models shared by every provider. Providers must return these, never raw JSON.

Modelos de datos: equipos, partidos, tablas y jugadores. Son el "idioma común" del bot:
- `providers/` convierte el JSON de cada API en estos objetos.
- `services/` y `cogs/` solo trabajan con estos objetos, nunca con JSON.
Así, si mañana cambiamos de API, solo cambia el provider y el resto del bot sigue igual.

Son `dataclass(frozen=True)`: objetos simples de solo lectura (no se pueden modificar después
de crearlos). `slots=True` los hace un poco más livianos en memoria.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

# Resultado de un partido desde el punto de vista de un equipo: ganó, empató o perdió.
Result = Literal["W", "D", "L"]


class MatchStatus:
    """football-data.org match statuses (kept as plain strings so unknown ones don't crash).

    Si la API inventa un estado nuevo, el bot no se rompe: simplemente no estará en
    ninguno de los grupos de abajo.
    """

    SCHEDULED = "SCHEDULED"  # programado, sin hora confirmada
    TIMED = "TIMED"  # programado, con hora confirmada
    IN_PLAY = "IN_PLAY"  # jugándose
    PAUSED = "PAUSED"  # medio tiempo
    EXTRA_TIME = "EXTRA_TIME"  # prórroga
    PENALTY_SHOOTOUT = "PENALTY_SHOOTOUT"  # penales
    FINISHED = "FINISHED"  # terminado
    SUSPENDED = "SUSPENDED"  # suspendido
    POSTPONED = "POSTPONED"  # aplazado
    CANCELLED = "CANCELLED"  # cancelado
    AWARDED = "AWARDED"  # resultado dado en mesa

    # Grupos de estados, para preguntar "¿está en vivo?" sin listar cada estado.
    LIVE = frozenset({IN_PLAY, PAUSED, EXTRA_TIME, PENALTY_SHOOTOUT})
    UPCOMING = frozenset({SCHEDULED, TIMED})
    DONE = frozenset({FINISHED, AWARDED})


@dataclass(frozen=True, slots=True)
class Competition:
    """Una liga o torneo. `code` es el código de football-data.org: PL, PD, CL..."""

    code: str
    name: str
    area: str  # país o región: "England", "Europe"...
    emblem: str | None = None  # URL del logo
    type: str = "LEAGUE"  # LEAGUE o CUP


@dataclass(frozen=True, slots=True)
class Player:
    """Un jugador de una plantilla. Se usará en la trivia de jugadores (Fase 3)."""

    id: int
    name: str
    position: str | None = None
    nationality: str | None = None
    date_of_birth: date | None = None


@dataclass(frozen=True, slots=True)
class Team:
    """Un equipo. Los partidos y las tablas solo traen id, nombres y escudo;
    `/team` (lookup completo) trae además el perfil: país, estadio, DT, etc."""

    id: int
    name: str  # nombre completo: "Real Madrid CF"
    short_name: str  # nombre corto: "Real Madrid" (es el que mostramos en tablas y partidos)
    tla: str | None = None  # siglas de 3 letras: "RMA"
    crest: str | None = None  # URL del escudo
    # Profile fields, only filled by team lookups
    country: str | None = None
    founded: int | None = None
    venue: str | None = None  # estadio
    colors: str | None = None
    website: str | None = None
    coach: str | None = None
    competitions: tuple[Competition, ...] = ()  # competiciones que juega esta temporada
    squad: tuple[Player, ...] = ()  # plantilla


@dataclass(frozen=True, slots=True)
class Match:
    """Un partido. `kickoff` siempre está en UTC; se pasa a la hora local al mostrarlo."""

    id: int
    competition: Competition
    kickoff: datetime  # fecha y hora de inicio, en UTC
    status: str  # uno de los valores de MatchStatus
    home: Team  # local
    away: Team  # visitante
    home_score: int | None = None  # None si todavía no empezó
    away_score: int | None = None
    matchday: int | None = None  # jornada
    stage: str | None = None  # fase: REGULAR_SEASON, LEAGUE_STAGE, FINAL...
    group: str | None = None  # grupo en torneos: GROUP_A...

    @property
    def is_live(self) -> bool:
        return self.status in MatchStatus.LIVE

    @property
    def is_finished(self) -> bool:
        return self.status in MatchStatus.DONE

    @property
    def is_upcoming(self) -> bool:
        return self.status in MatchStatus.UPCOMING

    def result_for(self, team_id: int) -> Result | None:
        """W/D/L from the point of view of `team_id`, or None if there is no final score.

        Se usa para la racha de `/team` (🟩🟨🟥). Devuelve None si el partido no terminó
        o si el equipo no jugó este partido.
        """
        if not self.is_finished or self.home_score is None or self.away_score is None:
            return None
        if team_id == self.home.id:
            ours, theirs = self.home_score, self.away_score
        elif team_id == self.away.id:
            ours, theirs = self.away_score, self.home_score
        else:
            return None
        if ours > theirs:
            return "W"
        return "D" if ours == theirs else "L"


@dataclass(frozen=True, slots=True)
class StandingRow:
    """Una fila de la tabla de posiciones."""

    position: int
    team: Team
    played: int  # PJ
    won: int  # G
    draw: int  # E
    lost: int  # P
    goals_for: int  # GF
    goals_against: int  # GC
    goal_difference: int  # DG
    points: int  # Pts


@dataclass(frozen=True, slots=True)
class Standing:
    """One table. Leagues have one, tournaments with groups have one per group.

    Ejemplo: la Premier devuelve 1 tabla de 20 filas; un Mundial en fase de grupos
    devuelve una tabla por grupo.
    """

    competition: Competition
    rows: tuple[StandingRow, ...]
    stage: str | None = None
    group: str | None = None
    matchday: int | None = None  # jornada actual de la temporada
