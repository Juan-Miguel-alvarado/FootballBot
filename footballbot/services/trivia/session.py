"""Estado de una partida de trivia en un canal: ronda actual, quién respondió y los puntos.

GameSession NO envía mensajes ni espera tiempos: eso lo hace cogs/trivia.py. Aquí solo están
las reglas, así se pueden probar sin Discord (tests/test_trivia_session.py).

Reglas:
- Cada ronda tiene 4 etapas (la imagen se va aclarando). Acertar antes da más puntos:
  STAGE_POINTS = 100, 75, 50, 25.
- El primero que acierta gana la ronda y la ronda se cierra.
- Botones: quien falla queda fuera de esa ronda. Escrito: se puede seguir intentando.
- Racha: rondas seguidas ganadas por el mismo jugador. Desde la segunda suma
  +10 por ronda de racha, hasta +50.
"""

import asyncio
from datetime import UTC, datetime
from enum import StrEnum

from footballbot.models import AnswerRecord, GameResult, PlayerScore, Question
from footballbot.services.trivia.matching import is_correct
from footballbot.services.trivia.modes import Mode

STAGE_POINTS = (100, 75, 50, 25)
STREAK_BONUS = 10
MAX_STREAK_BONUS = 50


class AnswerMode(StrEnum):
    BUTTONS = "buttons"
    TYPED = "typed"


class Outcome(StrEnum):
    CORRECT = "correct"
    WRONG = "wrong"
    ALREADY_TRIED = "already_tried"  # botones: ya respondió esta ronda
    CLOSED = "closed"  # la ronda ya terminó


class GameSession:
    def __init__(
        self,
        *,
        guild_id: int,
        channel_id: int,
        started_by: int,
        mode: Mode,
        difficulty: str,
        rounds: int,
        answer_mode: AnswerMode,
    ) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.started_by = started_by
        self.mode = mode
        self.difficulty = difficulty
        self.total_rounds = rounds
        self.answer_mode = answer_mode
        self.started_at = datetime.now(UTC)

        self.round = 0  # número de la ronda actual (empieza en 1 al llamar start_round)
        self.stage = 0  # etapa actual de la ronda (0 a 3)
        self.question: Question | None = None
        self.winner: int | None = None  # user_id de quien ganó la ronda actual
        self.round_open = False
        self.stopped = False
        self.scores: dict[int, PlayerScore] = {}
        self.answers: list[AnswerRecord] = []
        self._tried: set[int] = set()  # quién ya respondió (mal) con botones esta ronda
        # cogs/trivia.py espera este evento: se activa cuando alguien acierta o se para el juego
        self.round_over = asyncio.Event()

    # --- rondas ----------------------------------------------------------------------------

    @property
    def stages(self) -> int:
        return len(STAGE_POINTS)

    @property
    def finished(self) -> bool:
        return self.stopped or self.round >= self.total_rounds

    def start_round(self, question: Question) -> None:
        self.round += 1
        self.stage = 0
        self.question = question
        self.winner = None
        self.round_open = True
        self._tried.clear()
        self.round_over.clear()

    def next_stage(self) -> bool:
        """Pasa a la siguiente etapa. False si ya era la última."""
        if self.stage + 1 >= self.stages:
            return False
        self.stage += 1
        return True

    def close_round(self) -> None:
        """Termina la ronda: quien no la ganó pierde su racha."""
        self.round_open = False
        for score in self.scores.values():
            if score.user_id != self.winner:
                score.streak = 0
        self.round_over.set()

    def stop(self) -> None:
        """/trivia stop: termina la ronda actual y la partida."""
        self.stopped = True
        self.round_open = False
        self.round_over.set()

    # --- respuestas ------------------------------------------------------------------------

    def answer(
        self, user_id: int, *, choice_id: str | None = None, text: str | None = None
    ) -> tuple[Outcome, int]:
        """Registra una respuesta. Botones pasan `choice_id`; escrito pasa `text`.

        Devuelve (resultado, puntos ganados).
        """
        if not self.round_open or self.question is None:
            return Outcome.CLOSED, 0
        if user_id in self._tried:
            return Outcome.ALREADY_TRIED, 0

        answer = self.question.answer
        if choice_id is not None:
            correct = choice_id == answer.id
        else:
            correct = is_correct(text or "", answer.answers)

        score = self.scores.setdefault(user_id, PlayerScore(user_id))
        if not correct:
            if text is not None:
                # Escrito: un fallo es solo un mensaje más en el chat; no se guarda ni castiga
                return Outcome.WRONG, 0
            self._tried.add(user_id)
            score.answered += 1
            score.streak = 0
            self._record(user_id, correct=False, points=0)
            return Outcome.WRONG, 0

        score.streak += 1
        score.best_streak = max(score.best_streak, score.streak)
        bonus = min(STREAK_BONUS * (score.streak - 1), MAX_STREAK_BONUS)
        points = STAGE_POINTS[self.stage] + bonus
        score.points += points
        score.correct += 1
        score.answered += 1
        self._record(user_id, correct=True, points=points)
        self.winner = user_id
        self.close_round()
        return Outcome.CORRECT, points

    def _record(self, user_id: int, *, correct: bool, points: int) -> None:
        self.answers.append(
            AnswerRecord(
                round=self.round,
                user_id=user_id,
                correct=correct,
                stage=self.stage,
                points=points,
                answered_at=datetime.now(UTC),
            )
        )

    # --- resultados ------------------------------------------------------------------------

    def ranking(self) -> list[PlayerScore]:
        """Jugadores de más a menos puntos (a igual puntos, más aciertos primero)."""
        return sorted(self.scores.values(), key=lambda s: (-s.points, -s.correct))

    def result(self) -> GameResult:
        return GameResult(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            mode=self.mode.key,
            difficulty=self.difficulty,
            rounds=self.round,
            started_at=self.started_at,
            ended_at=datetime.now(UTC),
            answers=tuple(self.answers),
            players=tuple(self.ranking()),
        )
