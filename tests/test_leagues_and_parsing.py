"""Tests de las funciones pequeñas: búsqueda de ligas (services/leagues.py), normalize
(services/text.py) y los helpers de los comandos (cogs/common.py).

`@pytest.mark.parametrize` corre el mismo test con varios valores (una fila = un caso).
"""

from datetime import date

import discord
import pytest

from footballbot.cogs.common import image_url, pack_fields, parse_day, parse_league, split_lines
from footballbot.errors import UserFacingError
from footballbot.services.leagues import find_league, search_leagues
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
