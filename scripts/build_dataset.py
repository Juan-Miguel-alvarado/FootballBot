"""Arma el dataset de la trivia: data/dataset/teams.json y data/dataset/leagues.json.

Uso (desde la raíz del proyecto, con el .env lleno):
    python scripts/build_dataset.py

Qué hace:
1. Pide a football-data.org los equipos de cada competición de clubes (no Mundial ni Euro,
   que son selecciones). Tarda 1-2 minutos por el límite de 10 peticiones por minuto.
2. Le pone a cada equipo una dificultad según dónde juega (ver DIFFICULTY).
3. Comprueba que cada escudo exista en PNG (Discord y Pillow no leen SVG) y descarta los que no.
4. Escribe los JSON. Se suben al repo, así nadie más tiene que correr este script.

¿Cuándo volver a correrlo? Al empezar una temporada (equipos que suben y bajan) o si se
añade una liga en services/leagues.py. Los apodos NO van aquí: van en aliases.json, a mano.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

from footballbot.config import Settings
from footballbot.models import Team
from footballbot.providers.football_data import FootballDataProvider
from footballbot.services.leagues import LEAGUES, NATIONAL_TEAMS, TOP_5

log = logging.getLogger("build_dataset")

DATASET_DIR = Path(__file__).resolve().parent.parent / "data" / "dataset"

# Dificultad de un equipo según la competición: 1 fácil, 2 media, 3 difícil.
# Si juega varias (liga + Champions), se queda con la más fácil.
DIFFICULTY = {code: 1 for code in TOP_5} | {
    "DED": 2,
    "PPL": 2,
    "BSA": 2,
    "CL": 2,
    "ELC": 3,
    "CLI": 3,
}

# Comprobar escudos en paralelo, pero sin saturar el servidor de imágenes
CREST_CHECKS_AT_ONCE = 10


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Silencia el log de cada petición HTTP (son cientos)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()  # type: ignore[call-arg]
    provider = FootballDataProvider(settings.football_data_key.get_secret_value())
    try:
        teams, leagues = await _download(provider)
    finally:
        await provider.aclose()

    async with httpx.AsyncClient(timeout=10) as client:
        semaphore = asyncio.Semaphore(CREST_CHECKS_AT_ONCE)
        crests = await asyncio.gather(*(_png_url(client, semaphore, t["crest_url"]) for t in teams))
        emblems = await asyncio.gather(
            *(_png_url(client, semaphore, lg["emblem_url"]) for lg in leagues)
        )

    usable_teams = []
    for team, crest in zip(teams, crests, strict=True):
        if crest is None:
            log.warning("Skipping %s: no PNG crest", team["name"])
            continue
        usable_teams.append(team | {"crest_url": crest})
    usable_leagues = []
    for league, emblem in zip(leagues, emblems, strict=True):
        if emblem is None:
            log.warning("Skipping league %s: no PNG emblem", league["code"])
            continue
        usable_leagues.append(league | {"emblem_url": emblem})

    usable_teams.sort(key=lambda t: (t["difficulty"], t["name"]))
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    _write(DATASET_DIR / "teams.json", usable_teams)
    _write(DATASET_DIR / "leagues.json", usable_leagues)
    by_difficulty = {d: sum(t["difficulty"] == d for t in usable_teams) for d in (1, 2, 3)}
    log.info("teams.json: %d teams %s", len(usable_teams), by_difficulty)
    log.info("leagues.json: %d leagues", len(usable_leagues))


async def _download(provider: FootballDataProvider) -> tuple[list[dict], list[dict]]:
    """Equipos (sin repetir) de todas las competiciones de clubes, y los logos de las ligas."""
    teams: dict[int, dict] = {}
    for league in LEAGUES:
        # Selecciones nacionales: quedan para el modo `flag` (Fase 3)
        if league.code in NATIONAL_TEAMS:
            continue
        log.info("Downloading %s teams...", league.code)
        for team in await provider.competition_teams(league.code):
            entry = teams.setdefault(team.id, _team_entry(team))
            entry["leagues"].append(league.code)
            entry["difficulty"] = min(entry["difficulty"], DIFFICULTY[league.code])

    emblems = {c.code: c.emblem for c in await provider.competitions()}
    leagues = [
        {"code": lg.code, "name": lg.name, "area": lg.area, "emblem_url": emblems[lg.code]}
        for lg in LEAGUES
        if emblems.get(lg.code)
    ]
    return list(teams.values()), leagues


def _team_entry(team: Team) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "short_name": team.short_name,
        "tla": team.tla,
        "country": team.country,
        "leagues": [],
        "founded": team.founded,
        "venue": team.venue,
        "colors": team.colors,
        "crest_url": team.crest,
        "difficulty": 3,
    }


async def _png_url(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str | None
) -> str | None:
    """La URL del PNG si existe. Para un .svg prueba la misma ruta con .png."""
    if not url:
        return None
    candidate = url.removesuffix(".svg") + ".png" if url.endswith(".svg") else url
    async with semaphore:
        try:
            response = await client.head(candidate)
        except httpx.HTTPError:
            return None
    is_png = response.headers.get("content-type", "").startswith("image/png")
    return candidate if response.status_code == 200 and is_png else None


def _write(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
