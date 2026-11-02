"""Carga el dataset de la trivia desde data/dataset/ y lo convierte en TriviaItem.

Archivos:
- teams.json: los clubes. Lo genera `python scripts/build_dataset.py`; no se edita a mano.
- leagues.json: los logos de las ligas. Lo genera el mismo script.
- countries.json: países y selecciones, a mano (modos `flag` y `club-country`): código de
  flagcdn ("es", "gb-eng"), nombre como lo escribe la API, continente, dificultad y apodos.
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


# Banderas de flagcdn (sin key, sin límites). w640 = 640 px de ancho.
FLAG_URL = "https://flagcdn.com/w640/{code}.png"
# Inglaterra, Escocia y Gales tienen su propio emoji; Irlanda del Norte no (se usa el británico)
SUBDIVISION_EMOJI = {
    "gb-eng": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "gb-sct": "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "gb-wls": "🏴\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f",
    "gb-nir": "🇬🇧",
}


@dataclass(frozen=True, slots=True)
class TriviaDataset:
    teams: tuple[TriviaItem, ...]
    leagues: tuple[TriviaItem, ...]
    countries: tuple[TriviaItem, ...] = ()

    def country_of(self, team: TriviaItem) -> TriviaItem | None:
        """El país de un club, como TriviaItem (para el modo club-country)."""
        for country in self.countries:
            if country.name == team.country:
                return country
        return None


def load_dataset(directory: Path = DATASET_DIR) -> TriviaDataset:
    teams = _read(directory / "teams.json")
    leagues = _read(directory / "leagues.json")
    countries_path = directory / "countries.json"
    countries = _read(countries_path) if countries_path.exists() else []
    aliases_path = directory / "aliases.json"
    aliases = {entry["id"]: entry for entry in _read(aliases_path)} if aliases_path.exists() else {}

    unknown = aliases.keys() - {team["id"] for team in teams}
    if unknown:
        log.warning("aliases.json has ids that are not in teams.json: %s", sorted(unknown))

    dataset = TriviaDataset(
        teams=tuple(_team_item(team, aliases.get(team["id"])) for team in teams),
        leagues=tuple(_league_item(league) for league in leagues),
        countries=tuple(_country_item(country) for country in countries),
    )
    log.info(
        "Trivia dataset: %d teams, %d leagues, %d countries",
        len(dataset.teams),
        len(dataset.leagues),
        len(dataset.countries),
    )
    return dataset


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _team_item(team: dict, alias: dict | None) -> TriviaItem:
    display = alias["name"] if alias else team["short_name"]
    names = [team["name"], team["short_name"], display, *(alias["aliases"] if alias else ())]
    # La primera liga de la lista es la del país (el script recorre LEAGUES en orden)
    main_league = get_league(team["leagues"][0]) if team.get("leagues") else None
    subtitle = " · ".join(p for p in (team["country"], main_league and main_league.name) if p)
    return TriviaItem(
        id=f"team-{team['id']}",
        name=display,
        full_name=team["name"],
        answers=_answers(names),
        image_url=team["crest_url"],
        difficulty=team["difficulty"],
        country=team["country"],
        subtitle=subtitle or None,
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
        subtitle=league["area"],
    )


def _country_item(country: dict) -> TriviaItem:
    return TriviaItem(
        id=f"country-{country['code']}",
        name=country["name"],
        full_name=country["name"],
        answers=_answers([country["name"], *country["aliases"]]),
        image_url=FLAG_URL.format(code=country["code"]),
        difficulty=country["difficulty"],
        # En los países, `country` guarda el continente: las opciones falsas salen del mismo
        country=country["continent"],
        subtitle=country["continent"],
        emoji=flag_emoji(country["code"]),
    )


def flag_emoji(code: str) -> str:
    """ "es" -> 🇪🇸. Las letras del código se convierten en "letras indicadoras regionales"."""
    if code in SUBDIVISION_EMOJI:
        return SUBDIVISION_EMOJI[code]
    return "".join(chr(0x1F1E6 + ord(letter) - ord("a")) for letter in code.lower())


def _answers(names: list[str]) -> tuple[str, ...]:
    """Respuestas aceptadas, simplificadas y sin repetir (manteniendo el orden)."""
    return tuple(dict.fromkeys(s for s in (simplify(n) for n in names) if s))
