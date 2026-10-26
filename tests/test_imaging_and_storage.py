"""Tests de imágenes (imaging/) y de la base de datos (storage/).

Las imágenes se generan en memoria con Pillow, y la base de datos es un archivo temporal
(`tmp_path` lo crea pytest y lo borra al terminar).
"""

import io
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image

from footballbot.imaging.effects import SIZE, blur, pixelate, prepare, render_stage
from footballbot.imaging.loader import ImageDownloadError, ImageLoader
from footballbot.models import AnswerRecord, GameResult, PlayerScore
from footballbot.storage import repos
from footballbot.storage.db import Database, sqlite_path


def crest_png() -> bytes:
    """Un "escudo" de prueba: círculo rojo con transparencia alrededor."""
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for x in range(200):
        for y in range(200):
            if (x - 100) ** 2 + (y - 100) ** 2 < 80**2:
                image.putpixel((x, y), (200, 30, 30, 255) if x < 100 else (30, 30, 200, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# --- efectos -----------------------------------------------------------------------------------


def test_prepare_centers_on_square_background() -> None:
    image = prepare(crest_png())
    assert image.size == (SIZE, SIZE)
    assert image.mode == "RGB"
    # La esquina es fondo gris, no negro (la transparencia no se volvió negra)
    assert image.getpixel((0, 0)) != (0, 0, 0)


def test_pixelate_keeps_size_and_removes_detail() -> None:
    image = prepare(crest_png())
    pixelated = pixelate(image, 6)
    assert pixelated.size == image.size
    assert len(pixelated.getcolors(maxcolors=10_000) or []) <= 36  # 6 x 6 cuadros


def test_blur_keeps_size() -> None:
    image = prepare(crest_png())
    assert blur(image, 20).size == image.size


def test_render_stage_returns_png() -> None:
    for level in (6, None):
        png = render_stage(crest_png(), "pixelate", level)
        assert Image.open(io.BytesIO(png)).format == "PNG"


# --- descarga con caché ------------------------------------------------------------------------


async def test_loader_caches_on_disk(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, content=b"png-bytes", headers={"content-type": "image/png"})

    loader = ImageLoader(tmp_path, transport=httpx.MockTransport(handler))
    assert await loader.get("https://example.com/86.png") == b"png-bytes"
    assert await loader.get("https://example.com/86.png") == b"png-bytes"
    await loader.aclose()
    assert len(calls) == 1  # la segunda vez salió del disco
    assert len(list(tmp_path.iterdir())) == 1  # noqa: ASYNC240  (es un test, bloquear no importa)


async def test_loader_rejects_errors(tmp_path: Path) -> None:
    loader = ImageLoader(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(ImageDownloadError):
        await loader.get("https://example.com/missing.png")
    await loader.aclose()


# --- base de datos -----------------------------------------------------------------------------


def test_sqlite_path() -> None:
    assert sqlite_path("sqlite:///data/footballbot.db") == "data/footballbot.db"
    with pytest.raises(ValueError):
        sqlite_path("postgres://localhost/db")


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    await database.connect()
    yield database
    await database.close()


def game(guild_id: int, mode: str, players: list[PlayerScore]) -> GameResult:
    now = datetime.now(UTC)
    answers = tuple(
        AnswerRecord(round=1, user_id=p.user_id, correct=True, stage=0, points=p.points,
                     answered_at=now)
        for p in players
    )  # fmt: skip
    return GameResult(
        guild_id=guild_id,
        channel_id=5,
        mode=mode,
        difficulty="easy",
        rounds=3,
        started_at=now,
        ended_at=now,
        answers=answers,
        players=tuple(players),
    )


async def test_migrations_create_tables(db: Database) -> None:
    async with db.conn.execute("PRAGMA user_version") as cursor:
        assert (await cursor.fetchone())[0] == 1
    # Volver a migrar no hace nada (no falla por tablas que ya existen)
    await db.migrate()


async def test_leaderboard_adds_up_games_and_modes(db: Database) -> None:
    alice_crest = PlayerScore(100, points=200, correct=2, answered=3, best_streak=2)
    alice_blur = PlayerScore(100, points=50, correct=1, answered=1, best_streak=1)
    bob_blur = PlayerScore(200, points=300, correct=3, answered=3, best_streak=3)
    await repos.save_game(db, game(1, "crest", [alice_crest]))
    await repos.save_game(db, game(1, "blur", [alice_blur, bob_blur]))
    # Otro servidor: no cuenta
    await repos.save_game(db, game(2, "crest", [PlayerScore(300, points=999, correct=9)]))

    rows = await repos.leaderboard(db, guild_id=1)
    assert [(r.user_id, r.points, r.played) for r in rows] == [(200, 300, 1), (100, 250, 2)]
    assert rows[1].best_streak == 2

    crest_only = await repos.leaderboard(db, guild_id=1, mode="crest")
    assert [(r.user_id, r.points) for r in crest_only] == [(100, 200)]


async def test_save_game_stores_answers(db: Database) -> None:
    game_id = await repos.save_game(db, game(1, "crest", [PlayerScore(100, points=75)]))
    async with db.conn.execute("SELECT * FROM answers WHERE game_id = ?", (game_id,)) as cursor:
        rows = await cursor.fetchall()
    assert [(r["user_id"], r["points"], r["correct"]) for r in rows] == [(100, 75, 1)]
