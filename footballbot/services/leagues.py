"""Competitions the bot supports: the ones on football-data.org's free plan.

Catálogo de las 13 ligas y torneos que conoce el bot, con su código, bandera y apodos.
No hace peticiones a ninguna API: es una lista fija.

Quién lo usa:
- `/leagues` muestra esta lista (cogs/info.py).
- El autocompletado y `parse_league` de los comandos (cogs/common.py) buscan aquí.
- El orden de `LEAGUES` decide en qué orden salen las ligas en /matches y /live.
- `/standings` usa ZONES (los colores de cada tramo de la tabla) y COLORS (color del embed).

Para añadir una liga: agrega una línea `League(...)` en `LEAGUES` con el código que usa
football-data.org (la lista de códigos está en APIS.md), y si quieres, sus zonas y su color.
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


# --- zonas de la tabla (/standings) ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Zone:
    """Un tramo de la tabla con premio o castigo: puestos de Champions, descenso...

    `first` y `last` son posiciones. Los números negativos cuentan desde abajo:
    -3 es el antepenúltimo, -1 el último. Así sirve igual para ligas de 18 o de 20 equipos.
    """

    first: int
    last: int
    emoji: str
    label: str


# Colores de las zonas (los mismos en todas las ligas para que se entiendan de un vistazo)
UCL, UEL, UECL = "🔵", "🟠", "🟢"
PLAYOFF, DOWN, NONE = "🟡", "🔴", "⚪"

# Zonas por liga. Son las habituales de cada competición: pueden cambiar un poco cada
# temporada (por ejemplo, si el campeón de copa ya está clasificado). Para cambiarlas, edita aquí.
ZONES: dict[str, tuple[Zone, ...]] = {
    "PL": (Zone(1, 4, UCL, "Champions League"), Zone(5, 5, UEL, "Europa League"),
           Zone(6, 6, UECL, "Conference League"), Zone(-3, -1, DOWN, "Relegation")),
    "PD": (Zone(1, 4, UCL, "Champions League"), Zone(5, 6, UEL, "Europa League"),
           Zone(7, 7, UECL, "Conference League"), Zone(-3, -1, DOWN, "Relegation")),
    "SA": (Zone(1, 4, UCL, "Champions League"), Zone(5, 5, UEL, "Europa League"),
           Zone(6, 6, UECL, "Conference League"), Zone(-3, -1, DOWN, "Relegation")),
    "BL1": (Zone(1, 4, UCL, "Champions League"), Zone(5, 5, UEL, "Europa League"),
            Zone(6, 6, UECL, "Conference League"), Zone(-3, -3, PLAYOFF, "Relegation playoff"),
            Zone(-2, -1, DOWN, "Relegation")),
    "FL1": (Zone(1, 4, UCL, "Champions League"), Zone(5, 5, UEL, "Europa League"),
            Zone(6, 6, UECL, "Conference League"), Zone(-3, -3, PLAYOFF, "Relegation playoff"),
            Zone(-2, -1, DOWN, "Relegation")),
    "DED": (Zone(1, 2, UCL, "Champions League"), Zone(3, 3, UEL, "Europa League"),
            Zone(4, 4, UECL, "Conference League"), Zone(-3, -3, PLAYOFF, "Relegation playoff"),
            Zone(-2, -1, DOWN, "Relegation")),
    "PPL": (Zone(1, 2, UCL, "Champions League"), Zone(3, 3, UEL, "Europa League"),
            Zone(4, 4, UECL, "Conference League"), Zone(-3, -3, PLAYOFF, "Relegation playoff"),
            Zone(-2, -1, DOWN, "Relegation")),
    "ELC": (Zone(1, 2, UCL, "Promotion"), Zone(3, 6, PLAYOFF, "Promotion playoffs"),
            Zone(-3, -1, DOWN, "Relegation")),
    "BSA": (Zone(1, 4, UCL, "Copa Libertadores"), Zone(5, 6, PLAYOFF, "Libertadores qualifying"),
            Zone(7, 12, UECL, "Copa Sudamericana"), Zone(-4, -1, DOWN, "Relegation")),
    "CL": (Zone(1, 8, UCL, "Round of 16"), Zone(9, 24, PLAYOFF, "Knockout playoffs"),
           Zone(25, 36, DOWN, "Eliminated")),
    # Torneos con grupos: la zona se aplica dentro de cada grupo
    "CLI": (Zone(1, 2, UCL, "Next round"), Zone(3, 3, UECL, "Copa Sudamericana")),
    "WC": (Zone(1, 2, UCL, "Next round"),),
    "EC": (Zone(1, 2, UCL, "Next round"),),
}  # fmt: skip

# Color de la barra lateral del embed de cada liga (el de su marca, aproximado)
COLORS: dict[str, int] = {
    "PL": 0x3D195B, "PD": 0xFF4B44, "SA": 0x008FD7, "BL1": 0xD20515, "FL1": 0xDAE025,
    "DED": 0xF15A22, "PPL": 0x00A859, "ELC": 0x1C2C5B, "BSA": 0x00953B, "CL": 0x0E1E5B,
    "CLI": 0xC8A04B, "WC": 0x8A1538, "EC": 0x143CDB,
}  # fmt: skip


def zone_for(code: str, position: int, table_size: int) -> Zone | None:
    """La zona de una posición en la tabla de esa liga, o None si es mitad de tabla."""
    for zone in ZONES.get(code, ()):
        first = zone.first if zone.first > 0 else table_size + zone.first + 1
        last = zone.last if zone.last > 0 else table_size + zone.last + 1
        if first <= position <= last:
            return zone
    return None


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
