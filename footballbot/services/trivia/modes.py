"""Los modos de juego y cómo se arma cada pregunta.

Un modo dice: qué se adivina (clubes, ligas o países), qué efecto se le pone a la imagen
(pixelado, borroso, silueta, zoom...) y qué tan fuerte es el efecto en cada etapa.

Hay tres tipos (`kind`):
- "guess": se ve la imagen de la respuesta (el escudo del club, la bandera...) y hay que
  adivinarla. Es lo normal.
- "club-country": se ve el escudo de un club y hay que adivinar de qué país es.
- "mix": cada ronda usa uno de los modos de MIX_MODES al azar.

Para añadir un modo nuevo:
1. Si necesita un efecto nuevo, añádelo en imaging/effects.py (EFFECTS).
2. Añade una entrada en MODES aquí abajo. El comando /trivia start lo muestra solo.
"""

import random
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

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
    pool: str  # de dónde salen las respuestas: "teams", "leagues" o "countries"
    kind: str = "guess"  # "guess", "club-country" o "mix" (ver arriba)


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
    "silhouette": Mode(
        key="silhouette",
        title="Silhouette",
        prompt="Which club is this?",
        effect="silhouette",
        # Cuánto color asoma en cada etapa: al principio solo la forma
        levels=(0, 0.04, 0.12, 0.3),
        pool="teams",
    ),
    "zoom": Mode(
        key="zoom",
        title="Zoomed crest",
        prompt="Which club is this?",
        effect="zoom",
        # Qué parte del escudo se ve: empieza por un trocito y se va abriendo
        levels=(0.18, 0.3, 0.5, 0.8),
        pool="teams",
    ),
    "club-country": Mode(
        key="club-country",
        title="Club country",
        prompt="Which country is this club from?",
        effect="none",  # el escudo se ve entero: lo difícil es saber el país
        levels=(0, 0, 0, 0),
        pool="teams",
        kind="club-country",
    ),
    "flag": Mode(
        key="flag",
        title="Flags",
        prompt="Which national team is this?",
        effect="pixelate",
        levels=(5, 8, 14, 26),
        pool="countries",
    ),
    "mix": Mode(
        key="mix",
        title="Mix",
        prompt="Which club is this?",
        effect="pixelate",  # no se usa: cada ronda toma el efecto del modo que le toca
        levels=(6, 10, 16, 28),
        pool="teams",
        kind="mix",
    ),
}

# Los modos que pueden tocar en `mix` (todos los que muestran un escudo de club)
MIX_MODES = ("crest", "blur", "silhouette", "zoom")

# Dificultad -> nivel máximo de los clubes que entran.
# easy: solo las 5 grandes ligas. medium: + Holanda, Portugal, Brasil, Champions.
# hard: todo, incluido Championship y Libertadores. Ver DIFFICULTY en scripts/build_dataset.py.
DIFFICULTIES = {"easy": 1, "medium": 2, "hard": 3}


def pool_for(mode: Mode, dataset: TriviaDataset, difficulty: str) -> list[TriviaItem]:
    """Todo lo que puede salir en una partida de ese modo y dificultad."""
    if mode.pool == "leagues":
        return list(dataset.leagues)  # solo hay 13 ligas: la dificultad no aplica
    level = DIFFICULTIES[difficulty]
    if mode.pool == "countries":
        return [country for country in dataset.countries if country.difficulty <= level]
    teams = [team for team in dataset.teams if team.difficulty <= level]
    if mode.kind == "club-country":
        teams = [team for team in teams if dataset.country_of(team)]
    return teams


def make_picker(
    mode: Mode,
    dataset: TriviaDataset,
    difficulty: str,
    last_seen: Mapping[str, datetime] | None = None,
    rng: random.Random | None = None,
) -> "QuestionPicker":
    """El QuestionPicker que corresponde a cada tipo de modo."""
    pool = pool_for(mode, dataset, difficulty)
    if mode.kind == "club-country":
        return ClubCountryPicker(pool, dataset, rng, last_seen)
    if mode.kind == "mix":
        return MixPicker(pool, MIX_MODES, rng, last_seen)
    return QuestionPicker(pool, rng, last_seen)


class QuestionPicker:
    """Va sacando preguntas sin repetir la respuesta.

    Dentro de una partida nunca se repite una respuesta. Entre partidas, con `last_seen` (qué salió
    ya en este servidor y cuándo; viene de la base de datos, ver storage/repos.py):
    1. primero salen, en orden aleatorio, las respuestas que nunca salieron;
    2. cuando ya salieron todas, primero las que hace más tiempo que no salen.
    Es una "bolsa barajada con memoria": no se repite un escudo hasta agotar todos.
    """

    def __init__(
        self,
        pool: Sequence[TriviaItem],
        rng: random.Random | None = None,
        last_seen: Mapping[str, datetime] | None = None,
    ) -> None:
        if len(pool) < OPTIONS_PER_QUESTION:
            raise ValueError(f"need at least {OPTIONS_PER_QUESTION} items, got {len(pool)}")
        self._pool = list(pool)
        self._rng = rng or random.Random()
        last_seen = last_seen or {}

        shuffled = self._rng.sample(self._pool, len(self._pool))
        never_seen = [item for item in shuffled if item.id not in last_seen]
        seen = [item for item in shuffled if item.id in last_seen]
        # sort() mantiene el orden aleatorio entre los que salieron a la vez (misma partida)
        seen.sort(key=lambda item: last_seen[item.id])
        self._upcoming = deque(never_seen + seen)
        # Cuántas veces salió cada club como opción falsa en esta partida (para variar)
        self._option_uses: Counter[str] = Counter()

    @property
    def remaining(self) -> int:
        return len(self._upcoming)

    def next(self) -> Question:
        if not self._upcoming:
            raise IndexError("no more questions in this pool")
        return self._question(self._upcoming.popleft())

    def _question(self, item: TriviaItem) -> Question:
        """Arma la pregunta de `item`. Los pickers de otros tipos de modo cambian solo esto."""
        options = [item, *self._distractors(item, self._pool)]
        self._rng.shuffle(options)
        return Question(answer=item, options=tuple(options))

    def _distractors(self, answer: TriviaItem, pool: Sequence[TriviaItem]) -> list[TriviaItem]:
        """3 opciones falsas con nombres distintos entre sí y a la respuesta.

        Prefiere las que menos han salido como opción en esta partida, para que no se vean
        siempre los mismos clubes en los botones.
        """
        candidates = [item for item in pool if item.id != answer.id]
        self._rng.shuffle(candidates)
        # Menos usadas primero; entre las igual de usadas queda el orden aleatorio
        candidates.sort(key=lambda item: self._option_uses[item.id])
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
        self._option_uses.update(item.id for item in chosen)
        return chosen


class ClubCountryPicker(QuestionPicker):
    """Modo club-country: se ve el escudo de un club y las opciones son 4 países.

    Recorre los clubes con la misma memoria que los otros modos (no repite escudos).
    Las opciones falsas son países del mismo continente cuando se puede.
    """

    def __init__(
        self,
        pool: Sequence[TriviaItem],
        dataset: TriviaDataset,
        rng: random.Random | None = None,
        last_seen: Mapping[str, datetime] | None = None,
    ) -> None:
        super().__init__(pool, rng, last_seen)
        self._dataset = dataset

    def _question(self, item: TriviaItem) -> Question:
        country = self._dataset.country_of(item)
        assert country is not None  # pool_for solo deja clubes con país conocido
        options = [country, *self._distractors(country, self._dataset.countries)]
        self._rng.shuffle(options)
        return Question(answer=country, options=tuple(options), shown=item)


class MixPicker(QuestionPicker):
    """Modo mix: cada ronda le toca uno de `mode_keys` al azar (crest, blur, silhouette...)."""

    def __init__(
        self,
        pool: Sequence[TriviaItem],
        mode_keys: Sequence[str],
        rng: random.Random | None = None,
        last_seen: Mapping[str, datetime] | None = None,
    ) -> None:
        super().__init__(pool, rng, last_seen)
        self._mode_keys = list(mode_keys)

    def _question(self, item: TriviaItem) -> Question:
        question = super()._question(item)
        return replace(question, mode_key=self._rng.choice(self._mode_keys))
