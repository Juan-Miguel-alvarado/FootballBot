"""Tests del cliente de football-data.org (providers/football_data.py).

En vez de llamar a la API real, `FakeApi` responde con las respuestas reales guardadas en
tests/fixtures/football_data/ (grabadas el 2026-10-24). Así comprobamos que el JSON se convierte
bien en modelos, que la caché funciona y que los errores (404, 429) se manejan.

Para probar un endpoint nuevo: guarda su respuesta en fixtures/, añádela a ROUTES y escribe
un test como `test_team`.
"""

from datetime import UTC, date, datetime

import httpx
import pytest

from footballbot.providers import football_data
from footballbot.providers.base import NotFoundError, RateLimitedError
from footballbot.providers.football_data import FootballDataProvider
from tests.conftest import load_fixture

# Ruta de la API -> archivo de fixture con que responde FakeApi. Una ruta que no esté aquí da 404.
ROUTES = {
    "/v4/competitions": "football_data/competitions.json",
    "/v4/matches": "football_data/matches.json",
    "/v4/competitions/PL/standings": "football_data/standings_PL.json",
    "/v4/competitions/CL/standings": "football_data/standings_CL.json",
    "/v4/competitions/PD/teams": "football_data/teams_PD.json",
    "/v4/teams/86": "football_data/team_86.json",
    "/v4/teams/86/matches": "football_data/team_86_matches.json",
}


class FakeApi:
    """Serves the recorded fixtures and remembers every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []  # todas las peticiones recibidas
        # Respuestas forzadas: si hay alguna en la cola, se usa antes que ROUTES
        # (sirve para simular un 429).
        self.responses: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        fixture = ROUTES.get(request.url.path)
        if fixture is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=load_fixture(fixture))


# Las "fixtures" de pytest: cualquier test que tenga un parámetro `api` o `provider` los recibe
# creados por estas funciones (uno nuevo para cada test).
@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
async def provider(api: FakeApi):
    # MockTransport hace que httpx llame a FakeApi en vez de salir a internet.
    provider = FootballDataProvider("test-key", transport=httpx.MockTransport(api))
    yield provider
    await provider.aclose()


async def test_sends_auth_header(provider: FootballDataProvider, api: FakeApi) -> None:
    await provider.competitions()
    assert api.requests[0].headers["X-Auth-Token"] == "test-key"


async def test_competitions(provider: FootballDataProvider) -> None:
    competitions = {c.code: c for c in await provider.competitions()}
    assert {"PL", "PD", "SA", "BL1", "FL1", "CL", "CLI"} <= competitions.keys()
    assert competitions["PL"].area == "England"


async def test_standings(provider: FootballDataProvider) -> None:
    [table] = await provider.standings("PL")
    assert table.competition.code == "PL"
    assert len(table.rows) == 20
    first = table.rows[0]
    assert first.position == 1
    assert first.team.short_name == "Man City"
    assert first.points == 21
    assert first.won * 3 + first.draw == first.points
    assert table.matchday == 8


async def test_cup_standings_single_league_phase(provider: FootballDataProvider) -> None:
    [table] = await provider.standings("CL")
    assert table.stage == "LEAGUE_STAGE"


async def test_matches(provider: FootballDataProvider, api: FakeApi) -> None:
    matches = await provider.matches(date(2026, 10, 25), date(2026, 10, 25), competitions=["PL"])
    # dateTo is exclusive on the API, inclusive for us
    params = api.requests[0].url.params
    assert params["dateFrom"] == "2026-10-25"
    assert params["dateTo"] == "2026-10-26"
    assert params["competitions"] == "PL"

    match = next(m for m in matches if m.home.short_name == "Liverpool")
    assert match.competition.code == "PL"
    assert match.kickoff == datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
    assert match.is_upcoming
    assert match.home_score is None


async def test_team(provider: FootballDataProvider) -> None:
    team = await provider.team(86)
    assert team.name == "Real Madrid CF"
    assert team.venue == "Estadio Santiago Bernabéu"
    assert team.founded == 1902
    assert team.coach
    assert {c.code for c in team.competitions} == {"PD", "CL"}
    assert team.squad[0].date_of_birth is not None


async def test_team_matches_form(provider: FootballDataProvider) -> None:
    matches = await provider.team_matches(86, date(2026, 8, 25), date(2026, 11, 22))
    finished = [m for m in matches if m.is_finished]
    assert finished
    assert all(m.result_for(86) in {"W", "D", "L"} for m in finished)


async def test_competition_teams(provider: FootballDataProvider) -> None:
    names = [t.name for t in await provider.competition_teams("PD")]
    assert "FC Barcelona" in names


async def test_responses_are_cached(provider: FootballDataProvider, api: FakeApi) -> None:
    await provider.standings("PL")
    await provider.standings("PL")
    assert len(api.requests) == 1


async def test_not_found(provider: FootballDataProvider) -> None:
    with pytest.raises(NotFoundError):
        await provider.standings("WC")


async def test_retries_once_after_short_rate_limit(
    provider: FootballDataProvider, api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    # Reemplazamos asyncio.sleep para que el test no espere 5 s de verdad.
    monkeypatch.setattr(football_data.asyncio, "sleep", fake_sleep)
    api.responses.append(httpx.Response(429, headers={"X-RequestCounter-Reset": "5"}))
    await provider.competitions()
    assert slept == [5.0]
    assert len(api.requests) == 2


async def test_long_rate_limit_raises(provider: FootballDataProvider, api: FakeApi) -> None:
    api.responses.append(httpx.Response(429, headers={"X-RequestCounter-Reset": "59"}))
    with pytest.raises(RateLimitedError):
        await provider.competitions()


async def test_records_quota_left(provider: FootballDataProvider, api: FakeApi) -> None:
    api.responses.append(
        httpx.Response(
            200,
            json=load_fixture("football_data/competitions.json"),
            headers={"X-Requests-Available-Minute": "7"},
        )
    )
    await provider.competitions()
    assert provider.health().requests_left == 7
