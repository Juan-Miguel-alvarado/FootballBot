"""Carga el dataset de la trivia desde data/dataset/ y lo convierte en TriviaItem.

Archivos:
- teams.json: los clubes. Lo genera `python scripts/build_dataset.py`; no se edita a mano.
- leagues.json: los logos de las ligas. Lo genera el mismo script.
- aliases.json: apodos de los clubes, a mano. Cada entrada es
    {"id": 86, "name": "Real Madrid", "aliases": ["madrid", "los blancos", ...]}
  `id` es el id del club en teams.json. `name` es el nombre que se muestra en la trivia
  (si un club no tiene entrada, se usa su short_name de la API, ej. "Barça").
  Para añadir apodos solo edita ese archivo; no hace falta volver a correr el script.

Quién lo usa: cogs/trivia.py lo carga una vez al arrancar el bot.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from footballbot.models import TriviaItem
from footballbot.services.leagues import get_league
from footballbot.services.trivia.matching import simplify

log = logging.getLogger(__name__)

# footballbot/services/trivia/dataset.py -> raíz del proyecto -> data/dataset
DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "dataset"


@dataclass(frozen=True, slots=True)
class TriviaDataset:
    teams: tuple[TriviaItem, ...]
    leagues: tuple[TriviaItem, ...]


def load_dataset(directory: Path = DATASET_DIR) -> TriviaDataset:
    teams = _read(directory / "teams.json")
    leagues = _read(directory / "leagues.json")
    aliases_path = directory / "aliases.json"
    aliases = {entry["id"]: entry for entry in _read(aliases_path)} if aliases_path.exists() else {}

    unknown = aliases.keys() - {team["id"] for team in teams}
    if unknown:
        log.warning("aliases.json has ids that are not in teams.json: %s", sorted(unknown))

    dataset = TriviaDataset(
        teams=tuple(_team_item(team, aliases.get(team["id"])) for team in teams),
        leagues=tuple(_league_item(league) for league in leagues),
    )
    log.info("Trivia dataset: %d teams, %d leagues", len(dataset.teams), len(dataset.leagues))
    return dataset


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _team_item(team: dict, alias: dict | None) -> TriviaItem:
    display = alias["name"] if alias else team["short_name"]
    names = [team["name"], team["short_name"], display, *(alias["aliases"] if alias else ())]
    return TriviaItem(
        id=f"team-{team['id']}",
        name=display,
        full_name=team["name"],
        answers=_answers(names),
        image_url=team["crest_url"],
        difficulty=team["difficulty"],
        country=team["country"],
    )


def _league_item(league: dict) -> TriviaItem:
    # Los apodos de las ligas ya están en services/leagues.py ("epl", "laliga"...)
    known = get_league(league["code"])
    aliases = known.aliases if known else ()
    return TriviaItem(
        id=f"league-{league['code']}",
        name=league["name"],
        full_name=league["name"],
        answers=_answers([league["name"], league["code"], *aliases]),
        image_url=league["emblem_url"],
        difficulty=1,
        country=league["area"],
    )


def _answers(names: list[str]) -> tuple[str, ...]:
    """Respuestas aceptadas, simplificadas y sin repetir (manteniendo el orden)."""
    return tuple(dict.fromkeys(s for s in (simplify(n) for n in names) if s))
