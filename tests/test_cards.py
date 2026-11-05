"""Tests de las tarjetas en imagen (imaging/cards.py y imaging/draw.py) y de cómo las arma
cogs/info.py. No se descarga nada: los escudos son imágenes de prueba o faltan (None).
"""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from footballbot.imaging import cards
from footballbot.imaging.draw import fit_font, truncate
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
        cards.TableRow(
            i,
            f"Club {i}",
            crest() if with_crest else None,
            10,
            5,
            3,
            2,
            4,
            18,
            (66, 133, 244) if i <= 4 else None,
        )
        for i in range(1, count + 1)
    )


@pytest.mark.parametrize("count", [18, 20, 24, 36])
def test_standings_card_fits_every_row(count: int) -> None:
    group = cards.TableGroup(None, rows(count))
    width, height = png_size(
        cards.standings_card(
            title="League",
            subtitle="Standings",
            emblem=crest(),
            groups=[group],
            legend=[((66, 133, 244), "Champions League")],
        )
    )
    assert width == cards.WIDTH
    # Cabecera + columnas + una fila de al menos 40 px por equipo + leyenda
    assert height >= cards.HEADER_H + cards.COLUMNS_H + count * 40


def test_standings_card_with_groups_and_missing_crests() -> None:
    groups = [cards.TableGroup(f"Group {g}", rows(4, with_crest=False)) for g in "ABCD"]
    single = png_size(
        cards.standings_card(
            title="Cup",
            subtitle="",
            emblem=None,
            groups=[cards.TableGroup(None, rows(16, with_crest=False))],
        )
    )
    grouped = png_size(cards.standings_card(title="Cup", subtitle="", emblem=None, groups=groups))
    assert grouped[1] == single[1] + 4 * cards.GROUP_TITLE_H


def test_team_card_with_and_without_next_match() -> None:
    nxt = cards.NextMatch(crest(), None, "Barça", False, "Sun 25 Oct · 15:00", "La Liga")
    # Con partidos, la tarjeta completa; sin ninguno, una más baja con un solo aviso
    for next_match, form, height in ((nxt, ["W", "D", "L"], 660), (None, [], 470)):
        size = png_size(
            cards.team_card(
                name="Real Madrid",
                subtitle="Spain · Founded 1902",
                crest=crest(),
                facts=[("Stadium", "Bernabéu")],
                form=form,
                next_match=next_match,
            )
        )
        assert size == (cards.WIDTH, height)


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
    [png] = await cog._standings_image(get_league("PL"), [table])
    assert png_size(png)[0] == cards.WIDTH


def test_long_tables_are_split_into_pages() -> None:
    from footballbot.cogs.info import _pages

    assert len(_pages([cards.TableGroup(None, rows(20, with_crest=False))])) == 1
    pages = _pages([cards.TableGroup(None, rows(36, with_crest=False))])
    assert [len(p[0].rows) for p in pages] == [18, 18]
    groups = [cards.TableGroup(g, rows(4, with_crest=False)) for g in "ABCDEFGH"]
    assert _pages(groups) == [groups]  # los grupos van juntos


# --- tarjetas de la trivia (issue #11) ---------------------------------------------------------


def test_round_and_reveal_cards() -> None:
    from footballbot.imaging import trivia_cards as tc
    from footballbot.imaging.effects import render_stage

    stage = render_stage(crest(), "pixelate", 6)
    for current in range(4):
        size = png_size(
            tc.round_card(
                stage_image=stage,
                round_no=1,
                total_rounds=10,
                title="Crest",
                stage=current,
                points=(100, 75, 50, 25),
            )
        )
        assert size == (tc.WIDTH, 740)
    for success in (True, False):
        size = png_size(
            tc.reveal_card(
                crest=crest(),
                name="Real Madrid",
                subtitle="Spain · La Liga",
                headline="x got it +75",
                success=success,
            )
        )
        assert size == (tc.WIDTH, 700)


@pytest.mark.parametrize("count", [1, 2, 3, 7, 12])
def test_podium_and_leaderboard_with_any_number_of_players(count: int) -> None:
    from footballbot.imaging import trivia_cards as tc

    players = [tc.PlayerEntry(f"Player {i}", None, 100 - i, "1 correct") for i in range(count)]
    podium = png_size(tc.podium_card(title="Game over", subtitle="", players=players))
    board = png_size(tc.leaderboard_card(title="Leaderboard", subtitle="", players=players))
    assert podium[0] == board[0] == tc.WIDTH
    # El podio muestra hasta 10 (3 arriba + 7 en lista); el ranking crece con cada jugador
    assert board[1] == 150 + count * 76 + 70


def test_avatar_with_and_without_picture() -> None:
    from footballbot.imaging.draw import avatar

    assert avatar(None, 64, "Juan").size == (64, 64)
    picture = avatar(crest(), 64, "Juan")
    assert picture.mode == "RGBA"
    assert picture.getpixel((0, 0))[3] == 0  # la esquina queda transparente: es redondo


# --- estilo del logo del bot (issue #20) -------------------------------------------------------


def test_logo_has_a_transparent_background() -> None:
    from footballbot.imaging.draw import logo, shards

    image = logo(200)
    assert image.width == 200
    assert image.getpixel((0, image.height - 1))[3] == 0  # la esquina (antes negra) es transparente
    assert shards(80).width == 80
