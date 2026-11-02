"""Tests de las tarjetas en imagen (imaging/cards.py y imaging/draw.py) y de cómo las arma
cogs/info.py. No se descarga nada: los escudos son imágenes de prueba o faltan (None).
"""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from footballbot.imaging import cards
from footballbot.imaging.draw import color_from_names, fit_font, truncate
from footballbot.models import Competition, Standing
from footballbot.providers.football_data import _standing_row
from tests.conftest import load_fixture


def png_size(data: bytes) -> tuple[int, int]:
    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    return image.size


def crest() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (200, 200), (200, 30, 30, 255)).save(output, format="PNG")
    return output.getvalue()


def rows(count: int, with_crest: bool = True) -> tuple[cards.TableRow, ...]:
    return tuple(
        cards.TableRow(i, f"Club {i}", crest() if with_crest else None, 10, 5, 3, 2, 4, 18,
                       (66, 133, 244) if i <= 4 else None)
        for i in range(1, count + 1)
    )  # fmt: skip


@pytest.mark.parametrize("count", [18, 20, 24, 36])
def test_standings_card_fits_every_row(count: int) -> None:
    group = cards.TableGroup(None, rows(count))
    width, height = png_size(
        cards.standings_card(title="League", subtitle="Standings", accent=(61, 25, 91),
                             emblem=crest(), groups=[group],
                             legend=[((66, 133, 244), "Champions League")])
    )  # fmt: skip
    assert width == cards.WIDTH
    # Cabecera + columnas + una fila de al menos 40 px por equipo + leyenda
    assert height >= cards.HEADER_H + cards.COLUMNS_H + count * 40


def test_standings_card_with_groups_and_missing_crests() -> None:
    groups = [cards.TableGroup(f"Group {g}", rows(4, with_crest=False)) for g in "ABCD"]
    single = png_size(
        cards.standings_card(title="Cup", subtitle="", accent=(0, 0, 0), emblem=None,
                             groups=[cards.TableGroup(None, rows(16, with_crest=False))])
    )  # fmt: skip
    grouped = png_size(
        cards.standings_card(title="Cup", subtitle="", accent=(0, 0, 0), emblem=None,
                             groups=groups)
    )  # fmt: skip
    assert grouped[1] == single[1] + 4 * cards.GROUP_TITLE_H


def test_team_card_with_and_without_next_match() -> None:
    nxt = cards.NextMatch(crest(), None, "Barça", False, "Sun 25 Oct · 15:00", "La Liga")
    for next_match, form in ((nxt, ["W", "D", "L"]), (None, [])):
        size = png_size(
            cards.team_card(name="Real Madrid", subtitle="Spain · Founded 1902", crest=crest(),
                            accent=(110, 50, 160), facts=[("Stadium", "Bernabéu")], form=form,
                            next_match=next_match)
        )  # fmt: skip
        assert size == (cards.WIDTH, 640)


def test_color_from_names() -> None:
    assert color_from_names("White / Purple") == (110, 50, 160)
    assert color_from_names("Red / White") == (210, 35, 42)
    assert color_from_names("Black / White") == (85, 90, 105)  # solo neutros: gris oscuro
    assert color_from_names("Dark Blue / Yellow") == (0, 45, 120)
    assert color_from_names(None) == color_from_names("Weird colors")


def test_text_helpers() -> None:
    fnt = fit_font("A VERY LONG LEAGUE NAME INDEED", "title", "Bold", 54, 300, 20)
    assert fnt.getlength("A VERY LONG LEAGUE NAME INDEED") <= 300 or fnt.size == 20
    assert truncate("Wolverhampton Wanderers", fnt, 60).endswith("…")


# --- cómo lo arma cogs/info.py -----------------------------------------------------------------


async def test_info_cog_builds_the_standings_card_even_if_crests_fail() -> None:
    from footballbot.cogs.info import Info
    from footballbot.services.leagues import get_league

    async def no_images(url: str) -> bytes:
        raise OSError("offline")

    cog = Info.__new__(Info)  # sin arrancar el bot: solo lo que usa _standings_image
    cog.bot = SimpleNamespace(images=SimpleNamespace(get=no_images))
    data = load_fixture("football_data/standings_PL.json")
    table = Standing(
        Competition("PL", "Premier League", "England", data["competition"]["emblem"]),
        tuple(_standing_row(r) for r in data["standings"][0]["table"]),
        matchday=8,
    )
    png = await cog._standings_image(get_league("PL"), [table])
    assert png is not None
    assert png_size(png)[0] == cards.WIDTH


# --- tarjetas de la trivia (issue #11) ---------------------------------------------------------


def test_round_and_reveal_cards() -> None:
    from footballbot.imaging import trivia_cards as tc
    from footballbot.imaging.effects import render_stage

    stage = render_stage(crest(), "pixelate", 6)
    for current in range(4):
        size = png_size(
            tc.round_card(stage_image=stage, round_no=1, total_rounds=10, title="Crest",
                          accent=(52, 199, 89), stage=current, points=(100, 75, 50, 25))
        )  # fmt: skip
        assert size == (tc.WIDTH, 680)
    for success in (True, False):
        size = png_size(
            tc.reveal_card(crest=crest(), name="Real Madrid", subtitle="Spain · La Liga",
                           accent=(52, 199, 89), headline="x got it +75", success=success)
        )  # fmt: skip
        assert size == (tc.WIDTH, 600)


@pytest.mark.parametrize("count", [1, 2, 3, 7, 12])
def test_podium_and_leaderboard_with_any_number_of_players(count: int) -> None:
    from footballbot.imaging import trivia_cards as tc

    players = [tc.PlayerEntry(f"Player {i}", None, 100 - i, "1 correct") for i in range(count)]
    podium = png_size(tc.podium_card(title="Game over", subtitle="", accent=(0, 0, 0),
                                     players=players))  # fmt: skip
    board = png_size(tc.leaderboard_card(title="Leaderboard", subtitle="", accent=(0, 0, 0),
                                         players=players))  # fmt: skip
    assert podium[0] == board[0] == tc.WIDTH
    # El podio muestra hasta 10 (3 arriba + 7 en lista); el ranking crece con cada jugador
    assert board[1] == 140 + count * 76 + 30


def test_avatar_with_and_without_picture() -> None:
    from footballbot.imaging.draw import avatar

    assert avatar(None, 64, "Juan").size == (64, 64)
    picture = avatar(crest(), 64, "Juan")
    assert picture.mode == "RGBA"
    assert picture.getpixel((0, 0))[3] == 0  # la esquina queda transparente: es redondo
