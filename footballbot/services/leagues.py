"""Competitions the bot supports: the ones on football-data.org's free plan.

Catálogo de las 13 ligas y torneos que conoce el bot, con su código, bandera y apodos.
No hace peticiones a ninguna API: es una lista fija.

Quién lo usa:
- `/leagues` muestra esta lista (cogs/info.py).
- El autocompletado y `parse_league` de los comandos (cogs/common.py) buscan aquí.
- El orden de `LEAGUES` decide en qué orden salen las ligas en /matches y /live.

Para añadir una liga: agrega una línea `League(...)` en `LEAGUES` con el código que usa
football-data.org (la lista de códigos está en APIS.md).
"""

from dataclasses import dataclass

from footballbot.services.text import normalize


@dataclass(frozen=True, slots=True)
class League:
    code: str  # código de football-data.org: "PL"
    name: str  # nombre que mostramos: "Premier League"
    area: str  # país o región
    emoji: str  # bandera
    aliases: tuple[str, ...] = ()  # otras formas en que la gente la escribe


# Display order everywhere: top 5 first, then other leagues, then international cups
LEAGUES: tuple[League, ...] = (
    League("PL", "Premier League", "England", "🏴󠁧󠁢󠁥󠁮󠁧󠁿", ("epl", "premier")),
    League("PD", "La Liga", "Spain", "🇪🇸", ("laliga", "primera division")),
    League("SA", "Serie A", "Italy", "🇮🇹", ("calcio",)),
    League("BL1", "Bundesliga", "Germany", "🇩🇪", ("bundesliga",)),
    League("FL1", "Ligue 1", "France", "🇫🇷", ("ligue",)),
    League("DED", "Eredivisie", "Netherlands", "🇳🇱"),
    League("PPL", "Primeira Liga", "Portugal", "🇵🇹", ("liga portugal",)),
    League("ELC", "Championship", "England", "🏴󠁧󠁢󠁥󠁮󠁧󠁿", ("efl",)),
    League("BSA", "Brasileirão Série A", "Brazil", "🇧🇷", ("brasileirao", "brazil")),
    League("CL", "Champions League", "Europe", "🇪🇺", ("ucl", "champions")),
    League("CLI", "Copa Libertadores", "South America", "🌎", ("libertadores",)),
    League("WC", "FIFA World Cup", "World", "🌍", ("mundial", "world cup")),
    League("EC", "European Championship", "Europe", "🇪🇺", ("euro", "eurocopa")),
)

TOP_5 = ("PL", "PD", "SA", "BL1", "FL1")

# Índices para buscar rápido: código -> liga, y código -> posición en LEAGUES.
_BY_CODE = {league.code: league for league in LEAGUES}
_ORDER = {league.code: i for i, league in enumerate(LEAGUES)}


def get_league(code: str) -> League | None:
    """La liga con ese código exacto ("pl" o "PL"), o None."""
    return _BY_CODE.get(code.upper())


def league_order(code: str) -> int:
    """Sort key that follows LEAGUES; unknown codes go last."""
    return _ORDER.get(code, len(_ORDER))


def _keys(league: League) -> list[str]:
    """Todos los textos con los que se puede encontrar una liga, ya normalizados."""
    return [normalize(k) for k in (league.code, league.name, league.area, *league.aliases)]


def search_leagues(query: str) -> list[League]:
    """Leagues whose code, name, country or alias contains `query` (all of them if empty).

    Es lo que alimenta el autocompletado: "eng" -> Premier League y Championship.
    """
    q = normalize(query)
    if not q:
        return list(LEAGUES)
    return [league for league in LEAGUES if any(q in key for key in _keys(league))]


def find_league(query: str) -> League | None:
    """Best single match for a typed league: exact code or alias first, then a unique search hit.

    Se usa cuando el usuario escribe la liga a mano sin elegir una sugerencia.
    "premier" -> PL. Si el texto coincide con varias ligas, devuelve None (es ambiguo).
    """
    q = normalize(query)
    if not q:
        return None
    for league in LEAGUES:
        if q in _keys(league):
            return league
    hits = search_leagues(query)
    return hits[0] if len(hits) == 1 else None
