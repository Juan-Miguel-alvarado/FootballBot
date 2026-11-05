"""Tests de las funciones pequeñas: búsqueda de ligas (services/leagues.py), normalize
(services/text.py) y los helpers de los comandos (cogs/common.py).

`@pytest.mark.parametrize` corre el mismo test con varios valores (una fila = un caso).
"""

from datetime import date

import discord
import pytest

from footballbot.cogs.common import image_url, pack_fields, parse_day, parse_league, split_lines
from footballbot.errors import UserFacingError
from footballbot.services.leagues import find_league, search_leagues, zone_for
from footballbot.services.text import normalize


def test_normalize() -> None:
    assert normalize("  Atlético  de Madrid! ") == "atletico de madrid"


@pytest.mark.parametrize(
    ("query", "code"),
    [("PL", "PL"), ("pl", "PL"), ("premier", "PL"), ("La Liga", "PD"), ("brasileirao", "BSA")],
)
def test_find_league(query: str, code: str) -> None:
    league = find_league(query)
    assert league is not None and league.code == code


def test_find_league_unknown_or_ambiguous() -> None:
    assert find_league("") is None
    assert find_league("nothing like this") is None


def test_search_leagues() -> None:
    assert len(search_leagues("")) == 13
    assert {lg.code for lg in search_leagues("eng")} == {"PL", "ELC"}


def test_parse_league() -> None:
    assert parse_league(None) is None
    assert parse_league("serie a").code == "SA"
    with pytest.raises(UserFacingError):
        parse_league("nope")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, date(2026, 10, 24)),
        ("", date(2026, 10, 24)),
        ("tomorrow", date(2026, 10, 25)),
        ("Yesterday", date(2026, 10, 23)),
        ("2026-12-31", date(2026, 12, 31)),
        ("mañana", date(2026, 10, 25)),  # también en español
        ("hoy", date(2026, 10, 24)),
    ],
)
def test_parse_day(value: str | None, expected: date) -> None:
    assert parse_day(value, date(2026, 10, 24)) == expected


def test_parse_day_invalid() -> None:
    with pytest.raises(UserFacingError):
        parse_day("next friday", date(2026, 10, 24))


def test_image_url() -> None:
    assert image_url(None) is None
    assert image_url("https://crests.football-data.org/86.svg") == (
        "https://crests.football-data.org/86.png"
    )
    assert image_url("https://crests.football-data.org/PL.png").endswith("PL.png")


def test_split_lines() -> None:
    lines = ["x" * 40] * 30
    chunks = split_lines(lines, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert sum(c.count("x") for c in chunks) == 40 * 30


def test_pack_fields_spreads_over_embeds() -> None:
    base = discord.Embed(title="t")
    embeds = pack_fields(base, [("name", "v" * 1000)] * 12, max_chars=5500)
    assert len(embeds) == 3
    assert embeds[0] is base
    assert sum(len(e.fields) for e in embeds) == 12


# --- zonas de /standings -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "position", "size", "label"),
    [
        ("PL", 1, 20, "Champions League"),
        ("PL", 5, 20, "Europa League"),
        ("PL", 10, 20, None),  # mitad de tabla
        ("PL", 18, 20, "Relegation"),  # -3 en una liga de 20
        ("BL1", 16, 18, "Relegation playoff"),  # -3 en una liga de 18
        ("BL1", 18, 18, "Relegation"),
        ("CL", 24, 36, "Knockout playoffs"),
        ("XYZ", 1, 20, None),  # liga sin zonas
    ],
)
def test_zone_for(code: str, position: int, size: int, label: str | None) -> None:
    zone = zone_for(code, position, size)
    assert (zone.label if zone else None) == label


def test_standings_table_has_zone_emojis_and_legend() -> None:
    from footballbot.cogs.info import _leader_line, _table_block, _zone_legend
    from footballbot.models import Competition, Standing
    from footballbot.providers.football_data import _standing_row
    from tests.conftest import load_fixture

    data = load_fixture("football_data/standings_PL.json")
    rows = tuple(_standing_row(r) for r in data["standings"][0]["table"])
    table = Standing(Competition("PL", "Premier League", "England"), rows)

    lines = _table_block(table, "PL").splitlines()
    assert lines[0] == "```" and lines[-1] == "```"
    assert lines[2].startswith("🔵  1 Man City")
    assert lines[-2].startswith("🔴 20 ")
    assert _zone_legend("PL", [table]).startswith("🔵 Champions League")
    assert _leader_line(table).startswith("Leader: **Man City** · 21 pts")


# --- /matches, /live, /leagues y /ping más bonitos (issue #13) --------------------------------


def _group(code: str, count: int):
    from datetime import UTC, datetime

    from footballbot.models import Competition, Match, MatchStatus, Team
    from footballbot.services.football import MatchGroup

    comp = Competition(code, code, "X")
    matches = tuple(
        Match(i, comp, datetime(2026, 11, 1, 15, tzinfo=UTC), MatchStatus.FINISHED,
              Team(1, "Arsenal", "Arsenal"), Team(2, "Chelsea", "Chelsea"), 2, 1)
        for i in range(count)
    )  # fmt: skip
    return MatchGroup(comp, matches)


def test_league_embeds_respect_discord_limits() -> None:
    from zoneinfo import ZoneInfo

    from footballbot.cogs.common import MAX_EMBEDS_PER_MESSAGE, MAX_FIELDS
    from footballbot.cogs.info import _league_embeds

    codes = ["PL", "PD", "SA", "BL1", "FL1", "DED", "PPL", "ELC", "BSA", "CL", "CLI", "WC", "EC"]
    groups = [_group(code, 12) for code in codes]
    batches = _league_embeds(groups, ZoneInfo("UTC"), title="Matches", empty="none",
                             footer="footer")  # fmt: skip
    embeds = [e for batch in batches for e in batch]
    # Una sección (campo) por liga, repartidas en los embeds que hagan falta
    assert sum(len(e.fields) for e in embeds) == len(codes)
    for batch in batches:
        assert len(batch) <= MAX_EMBEDS_PER_MESSAGE
        assert sum(len(e) for e in batch) <= 6000  # límite de Discord por mensaje
        assert all(len(e.fields) <= MAX_FIELDS for e in batch)
    assert embeds[0].description == "**156** matches · 13 competitions"
    assert embeds[0].fields[0].name == "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League"
    assert embeds[-1].footer.text == "footer"


def test_single_league_uses_its_logo_and_a_plain_section_name() -> None:
    from zoneinfo import ZoneInfo

    from footballbot.cogs.info import _league_embeds

    [[embed]] = _league_embeds([_group("PL", 3)], ZoneInfo("UTC"), title="PL", empty="none",
                               footer="f", single=True)  # fmt: skip
    assert embed.description == "**3** matches"
    assert embed.fields[0].name == "Fixtures"


def test_finished_match_shows_the_winner_in_bold() -> None:
    from zoneinfo import ZoneInfo

    from footballbot.cogs.info import _match_line

    line = _match_line(_group("PL", 1).matches[0], ZoneInfo("UTC"))
    assert line == "FT · **Arsenal** 2\u20131 Chelsea"


def test_leagues_by_region() -> None:
    from footballbot.cogs.info import _leagues_by_region

    regions = dict(_leagues_by_region())
    assert {lg.code for lg in regions["International"]} == {"CL", "WC", "EC"}
    assert {lg.code for lg in regions["South America"]} == {"BSA", "CLI"}
    assert sum(len(v) for v in regions.values()) == 13


def test_ping_colors() -> None:
    from footballbot.cogs.admin import _latency_color
    from footballbot.cogs.common import COLOR

    fast, normal, slow = (_latency_color(ms) for ms in (50, 200, 900))
    assert fast != COLOR  # rápido: verde, como el punto de estado
    assert len({fast.value, normal.value, slow.value}) == 3


def test_similar_team_names_for_typos() -> None:
    from footballbot.models import Team
    from footballbot.services.football import FootballService

    service = FootballService.__new__(FootballService)  # solo el índice de equipos
    service._teams = {
        1: Team(1, "FC Barcelona", "Barça"),
        2: Team(2, "Real Madrid CF", "Real Madrid"),
    }
    assert service.similar_teams("barcelna") == ["Barça"]
    assert service.similar_teams("nonexistent fc") == []


def test_leagues_sorted_by_importance() -> None:
    from footballbot.services.leagues import league_order

    codes = sorted(["ELC", "PL", "CL", "BSA", "WC", "XYZ"], key=league_order)
    assert codes == ["WC", "CL", "PL", "BSA", "ELC", "XYZ"]
