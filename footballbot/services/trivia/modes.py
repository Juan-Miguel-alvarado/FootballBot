"""Los modos de juego y cómo se arma cada pregunta.

Un modo dice: qué se adivina (clubes o ligas), qué efecto se le pone a la imagen
(pixelado o borroso) y qué tan fuerte es el efecto en cada etapa.

Para añadir un modo nuevo (ej. `silhouette` en la Fase 3):
1. Añade el efecto en imaging/effects.py y regístralo en `apply`.
2. Añade una entrada en MODES aquí abajo. El comando /trivia start lo muestra solo.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from footballbot.models import Question, TriviaItem
from footballbot.services.trivia.dataset import TriviaDataset

OPTIONS_PER_QUESTION = 4
# Cuántas opciones falsas intentamos que sean del mismo país (más difícil de descartar)
SAME_COUNTRY_DISTRACTORS = 2


@dataclass(frozen=True, slots=True)
class Mode:
    key: str  # lo que se escribe en el comando: "crest"
    title: str  # lo que se muestra: "Pixelated crest"
    prompt: str  # la pregunta de cada ronda
    effect: str  # nombre del efecto en imaging/effects.py: "pixelate" o "blur"
    # Intensidad del efecto en cada etapa, de la más difícil a la más fácil.
    # pixelate: cuántos "bloques" de ancho tiene la imagen. blur: radio del desenfoque.
    levels: tuple[float, ...]
    pool: str  # de dónde salen las respuestas: "teams" o "leagues"


MODES: dict[str, Mode] = {
    "crest": Mode(
        key="crest",
        title="Pixelated crest",
        prompt="Which club is this?",
        effect="pixelate",
        levels=(6, 10, 16, 28),
        pool="teams",
    ),
    "blur": Mode(
        key="blur",
        title="Blurred crest",
        prompt="Which club is this?",
        effect="blur",
        levels=(32, 20, 12, 6),
        pool="teams",
    ),
    "league": Mode(
        key="league",
        title="League logo",
        prompt="Which competition is this?",
        effect="pixelate",
        levels=(6, 10, 16, 28),
        pool="leagues",
    ),
}

# Dificultad -> nivel máximo de los clubes que entran.
# easy: solo las 5 grandes ligas. medium: + Holanda, Portugal, Brasil, Champions.
# hard: todo, incluido Championship y Libertadores. Ver DIFFICULTY en scripts/build_dataset.py.
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}


def pool_for(mode: Mode, dataset: TriviaDataset, difficulty: str) -> list[TriviaItem]:
    """Todo lo que puede salir en una partida de ese modo y dificultad."""
    if mode.pool == "leagues":
        return list(dataset.leagues)  # solo hay 13 ligas: la dificultad no aplica
    level = DIFFICULTIES[difficulty]
    return [team for team in dataset.teams if team.difficulty <= level]


class QuestionPicker:
    """Va sacando preguntas sin repetir la respuesta dentro de una misma partida."""

    def __init__(self, pool: Sequence[TriviaItem], rng: random.Random | None = None) -> None:
        if len(pool) < OPTIONS_PER_QUESTION:
            raise ValueError(f"need at least {OPTIONS_PER_QUESTION} items, got {len(pool)}")
        self._pool = list(pool)
        self._rng = rng or random.Random()
        # Orden aleatorio de las respuestas; se van sacando de a una
        self._upcoming = self._rng.sample(self._pool, len(self._pool))

    @property
    def remaining(self) -> int:
        return len(self._upcoming)

    def next(self) -> Question:
        if not self._upcoming:
            raise IndexError("no more questions in this pool")
        answer = self._upcoming.pop()
        options = [answer, *self._distractors(answer)]
        self._rng.shuffle(options)
        return Question(answer=answer, options=tuple(options))

    def _distractors(self, answer: TriviaItem) -> list[TriviaItem]:
        """3 opciones falsas con nombres distintos entre sí y a la respuesta."""
        candidates = [item for item in self._pool if item.id != answer.id]
        self._rng.shuffle(candidates)
        # Primero hasta 2 del mismo país, luego cualquiera
        same_country = [c for c in candidates if c.country == answer.country]
        first = same_country[:SAME_COUNTRY_DISTRACTORS]
        ordered = first + [c for c in candidates if c not in first]

        chosen: list[TriviaItem] = []
        names = {answer.name}
        for item in ordered:
            if item.name in names:
                continue  # ej. dos "Liverpool": no pueden salir juntos en los botones
            chosen.append(item)
            names.add(item.name)
            if len(chosen) == OPTIONS_PER_QUESTION - 1:
                break
        return chosen
