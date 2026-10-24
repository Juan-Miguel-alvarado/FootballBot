"""Tests de la lógica de services/football.py, sin Discord y sin API.

`FakeProvider` imita al provider real: devuelve los partidos o equipos que el test le pone
y anota las llamadas que recibe, para comprobar qué se le pidió (fechas, filtros...).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from footballbot.errors import UserFacingError
from footballbot.models import Competition, Match, MatchStatus, Standing, Team
from footballbot.providers.base import ProviderError, ProviderHealth
from footballbot.services.football import FootballService

# Datos de ejemplo para los tests.
BOGOTA = ZoneInfo("America/Bogota")
PL = Competition("PL", "Premier League", "England")
BSA = Competition("BSA", "Campeonato Brasileiro Série A", "Brazil")
CL = Competition("CL", "UEFA Champions League", "Europe")

ARSENAL = Team(81, "Arsenal FC", "Arsenal", "ARS")
CHELSEA = Team(61, "Chelsea FC", "Chelsea", "CHE")
ATLETI = Team(78, "Club Atlético de Madrid", "Atleti", "ATM")
REAL = Team(86, "Real Madrid CF", "Real Madrid", "RMA")
SANTOS = Team(6685, "Santos FC", "Santos", "SAN")


def match(
    id: int,
    comp: Competition,
    kickoff: datetime,
    home: Team = ARSENAL,
    away: Team = CHELSEA,
    status: str = MatchStatus.TIMED,
    score: tuple[int, int] | None = None,
) -> Match:
    """Crea un partido de prueba con valores por defecto (Arsenal vs Chelsea, por jugar)."""
    return Match(
        id=id,
        competition=comp,
        kickoff=kickoff,
        status=status,
        home=home,
        away=away,
        home_score=score[0] if score else None,
        away_score=score[1] if score else None,
    )


class FakeProvider:
    """Provider falso: el test llena `matches_result`, `team_matches_result` o `teams`."""

    def __init__(self) -> None:
        self.matches_result: list[Match] = []
        self.team_matches_result: list[Match] = []
        self.teams: dict[str, list[Team]] = {}
        self.calls: list[tuple] = []

    async def competitions(self) -> list[Competition]:
        return [PL]

    async def matches(
        self,
        date_from: date,
        date_to: date,
        *,
        competitions: Sequence[str] | None = None,
        status: str | None = None,
    ) -> list[Match]:
        self.calls.append(("matches", date_from, date_to, competitions, status))
        return self.matches_result

    async def team_matches(self, team_id: int, date_from: date, date_to: date) -> list[Match]:
        return self.team_matches_result

    async def standings(self, competition: str) -> list[Standing]:
        return []

    async def team(self, team_id: int) -> Team:
        return REAL

    async def competition_teams(self, competition: str) -> list[Team]:
        if competition not in self.teams:
            raise ProviderError("boom")
        return self.teams[competition]

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake")

    async def aclose(self) -> None:
        pass


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def service(provider: FakeProvider) -> FootballService:
    return FootballService(provider, BOGOTA)


async def test_matches_on_uses_local_day(service: FootballService, provider: FakeProvider) -> None:
    provider.matches_result = [
        # 20:00 in Bogota on the 24th, already the 25th in UTC
        match(1, BSA, datetime(2026, 10, 25, 1, 0, tzinfo=UTC), SANTOS, CHELSEA),
        match(2, PL, datetime(2026, 10, 24, 14, 0, tzinfo=UTC)),
        # 23:00 in Bogota on the 23rd: previous local day
        match(3, PL, datetime(2026, 10, 24, 4, 0, tzinfo=UTC)),
        # 00:30 in Bogota on the 25th: next local day
        match(4, PL, datetime(2026, 10, 25, 5, 30, tzinfo=UTC)),
    ]
    groups = await service.matches_on(date(2026, 10, 24))

    _, date_from, date_to, competitions, _ = provider.calls[0]
    assert (date_from, date_to) == (date(2026, 10, 24), date(2026, 10, 25))
    assert competitions is None
    # Leagues follow the LEAGUES order: PL before BSA
    assert [g.competition.code for g in groups] == ["PL", "BSA"]
    assert [m.id for g in groups for m in g.matches] == [2, 1]


async def test_matches_on_filters_league(service: FootballService, provider: FakeProvider) -> None:
    await service.matches_on(date(2026, 10, 24), "PL")
    assert provider.calls[0][3] == ["PL"]


async def test_live_only_returns_live(service: FootballService, provider: FakeProvider) -> None:
    now = datetime.now(UTC)
    provider.matches_result = [
        match(1, PL, now, status=MatchStatus.IN_PLAY, score=(1, 0)),
        match(2, PL, now, status=MatchStatus.FINISHED, score=(2, 2)),
    ]
    groups = await service.live()
    assert provider.calls[0][4] == "LIVE"
    assert [m.id for g in groups for m in g.matches] == [1]


async def test_team_profile_form_and_next(service: FootballService, provider: FakeProvider) -> None:
    now = datetime.now(UTC)
    provider.team_matches_result = [
        match(i, PL, now - timedelta(days=10 - i), REAL, CHELSEA, MatchStatus.FINISHED, (i % 3, 1))
        for i in range(7)
    ] + [match(99, CL, now + timedelta(days=3), ARSENAL, REAL)]
    profile = await service.team_profile("86")

    assert profile.team is REAL
    assert [m.id for m in profile.recent] == [2, 3, 4, 5, 6]
    assert [m.result_for(86) for m in profile.recent] == ["W", "L", "D", "W", "L"]
    assert profile.next_match is not None and profile.next_match.id == 99


async def test_team_profile_unknown(service: FootballService) -> None:
    with pytest.raises(UserFacingError):
        await service.team_profile("nonexistent fc")


async def test_search_teams(service: FootballService) -> None:
    service.add_teams([ARSENAL, CHELSEA, ATLETI, REAL])
    assert [t.id for t in service.search_teams("atletico")] == [78]
    assert [t.id for t in service.search_teams("ATM")] == [78]
    # Prefix matches rank before matches inside the name
    assert [t.id for t in service.search_teams("real")] == [86]
    assert [t.id for t in service.search_teams("madrid")] == [78, 86]
    assert len(service.search_teams("")) == 4
    assert service.search_teams("xyz") == []


async def test_resolve_team_id(service: FootballService) -> None:
    service.add_teams([ARSENAL])
    assert service.resolve_team_id("81") == 81
    assert service.resolve_team_id("arsenal") == 81
    assert service.resolve_team_id("nope") is None


async def test_refresh_team_index_skips_failures(
    service: FootballService, provider: FakeProvider
) -> None:
    provider.teams = {"PL": [ARSENAL, CHELSEA]}
    await service.refresh_team_index(["PL", "PD"], delay=0)
    assert service.indexed_teams == 2


def test_result_for() -> None:
    m = match(1, PL, datetime.now(UTC), status=MatchStatus.FINISHED, score=(2, 1))
    assert m.result_for(ARSENAL.id) == "W"
    assert m.result_for(CHELSEA.id) == "L"
    assert m.result_for(REAL.id) is None
    assert match(2, PL, datetime.now(UTC)).result_for(ARSENAL.id) is None
