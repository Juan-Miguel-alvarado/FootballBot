"""Modelos de la trivia: qué se adivina, cómo es una pregunta y el resultado de una partida.

Quién los usa: services/trivia/ (dataset, modos, sesión), storage/ (guarda GameResult)
y cogs/trivia.py.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TriviaItem:
    """Algo que se puede adivinar: un club (modos crest y blur) o una liga (modo league)."""

    id: str  # "team-86" o "league-PL"
    name: str  # nombre que se muestra al revelar y en los botones: "Real Madrid"
    full_name: str  # nombre completo, para desempatar botones con nombres repetidos
    answers: tuple[str, ...]  # todo lo que cuenta como respuesta correcta, ya normalizado
    image_url: str  # escudo o logo en PNG
    difficulty: int  # 1 fácil, 2 media, 3 difícil
    country: str | None = None  # para elegir opciones falsas parecidas (mismo país)


@dataclass(frozen=True, slots=True)
class Question:
    """Una ronda: la respuesta correcta y las 4 opciones de los botones (ya mezcladas)."""

    answer: TriviaItem
    options: tuple[TriviaItem, ...]


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """Una respuesta de un jugador en una ronda. Se guarda en la tabla `answers`."""

    round: int
    user_id: int
    correct: bool
    stage: int  # en qué etapa respondió (0 = la imagen más difícil)
    points: int
    answered_at: datetime


@dataclass(slots=True)
class PlayerScore:
    """Cómo le va a un jugador en la partida actual. Cambia durante el juego (no es frozen)."""

    user_id: int
    points: int = 0
    correct: int = 0
    answered: int = 0
    streak: int = 0  # rondas seguidas ganadas ahora mismo
    best_streak: int = 0


@dataclass(frozen=True, slots=True)
class GameResult:
    """Todo lo que se guarda en la base de datos al terminar una partida."""

    guild_id: int
    channel_id: int
    mode: str
    difficulty: str
    rounds: int  # rondas jugadas de verdad (menos que las pedidas si alguien la paró)
    started_at: datetime
    ended_at: datetime
    answers: tuple[AnswerRecord, ...] = ()
    players: tuple[PlayerScore, ...] = ()
