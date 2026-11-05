"""Genera docs/preview.gif: una vista previa animada del bot para el README.

Uso (desde la raíz del proyecto, con el .env lleno):
    python scripts/make_preview.py

No es una grabación de Discord: son las mismas imágenes que manda el bot (tarjetas de la
trivia, tabla, perfil de equipo), generadas con datos reales y unidas en un GIF.
Vuelve a correrlo cuando cambie el diseño de las tarjetas (imaging/).
Gasta unas 4 peticiones de la API de football-data.org.
"""

import asyncio
import io
import logging
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from footballbot.cogs.info import Info
from footballbot.config import Settings
from footballbot.imaging import trivia_cards
from footballbot.imaging.draw import BLACK
from footballbot.imaging.effects import render_stage
from footballbot.imaging.loader import ImageLoader
from footballbot.providers.football_data import FootballDataProvider
from footballbot.services.football import FootballService
from footballbot.services.leagues import get_league
from footballbot.services.trivia.dataset import load_dataset
from footballbot.services.trivia.modes import MODES
from footballbot.services.trivia.session import STAGE_POINTS

STAGE_SECONDS = 5  # como en cogs/trivia.py: cada cuánto se aclara la imagen
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "preview.gif"
FRAME = (640, 544)  # tamaño de cada cuadro (la tarjeta de ronda es 800x680)
STAGE_MS = 650  # cuánto dura cada etapa en el GIF
CARD_MS = 2200  # cuánto dura cada tarjeta "quieta" (respuesta, podio, tabla...)

# Nombres de ejemplo para el podio (no son jugadores reales)
PLAYERS = [("Messi10", 340), ("ElBicho", 260), ("Pibe", 175), ("Cholo", 75), ("Tiki", 50)]


def frame(png: bytes, crop_top: bool = False) -> Image.Image:
    """Encaja una imagen en el tamaño del GIF. `crop_top`: se queda con la parte de arriba."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    if crop_top:
        # Tarjetas altas (la tabla): se corta con la misma proporción que el cuadro
        height = round(image.width * FRAME[1] / FRAME[0])
        image = image.crop((0, 0, image.width, min(height, image.height)))
    image.thumbnail(FRAME, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", FRAME, BLACK)
    canvas.paste(image, ((FRAME[0] - image.width) // 2, (FRAME[1] - image.height) // 2))
    return canvas


def trivia_round(
    image: bytes,
    mode_key: str,
    round_no: int,
    name: str,
    subtitle: str | None,
    headline: str,
    points: int,
    stages: int,
) -> list[tuple[Image.Image, int]]:
    """Las etapas de una ronda (cada vez más clara) y la tarjeta de la respuesta."""
    mode = MODES[mode_key]
    frames = []
    for stage in range(stages):
        stage_image = render_stage(image, mode.effect, mode.levels[stage], seed=round_no)
        card = trivia_cards.round_card(
            stage_image=stage_image, round_no=round_no, total_rounds=10, title=mode.title,
            stage=stage, points=STAGE_POINTS, prompt=mode.prompt, seconds=STAGE_SECONDS,
            cue={"zoom": "WIDER", "silhouette": "COLOR"}.get(mode.effect),
        )  # fmt: skip
        frames.append((frame(card), STAGE_MS))
    reveal = trivia_cards.reveal_card(
        crest=image,
        name=name,
        subtitle=subtitle,
        headline=headline,
        success=True,
        label=f"Round {round_no}/10",
        points=points,
    )
    frames.append((frame(reveal), CARD_MS))
    return frames


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    settings = Settings()  # type: ignore[call-arg]
    provider = FootballDataProvider(settings.football_data_key.get_secret_value())
    images = ImageLoader()
    football = FootballService(provider, settings.tz)
    # El cog de info sin arrancar el bot: solo para usar sus funciones de tarjetas
    info = Info.__new__(Info)
    info.bot = SimpleNamespace(images=images)
    info.football = football

    dataset = load_dataset()
    teams = {t.id: t for t in dataset.teams}
    countries = {c.id: c for c in dataset.countries}
    try:
        real, barca, boca = (teams["team-86"], teams["team-81"], teams["team-2061"])
        liverpool, brazil = teams["team-64"], countries["country-br"]
        crests = {
            item.id: await images.get(item.image_url)
            for item in (real, barca, boca, liverpool, brazil)
        }
        frames: list[tuple[Image.Image, int]] = []
        frames += trivia_round(crests[real.id], "crest", 1, real.name, real.subtitle,
                               "Messi10 got it", 75, 4)  # fmt: skip
        frames += trivia_round(crests[barca.id], "silhouette", 2, barca.name, barca.subtitle,
                               "ElBicho got it", 50, 4)  # fmt: skip
        frames += trivia_round(crests[liverpool.id], "zoom", 3, liverpool.name,
                               liverpool.subtitle, "Pibe got it", 75, 3)  # fmt: skip
        argentina = dataset.country_of(boca)
        frames += trivia_round(crests[boca.id], "club-country", 4, argentina.name, boca.name,
                               "Messi10 got it", 100, 1)  # fmt: skip
        frames += trivia_round(crests[brazil.id], "flag", 5, brazil.name, brazil.subtitle,
                               "Cholo got it", 50, 3)  # fmt: skip

        podium = trivia_cards.podium_card(
            title="Game over", subtitle="Mix · 10 rounds · easy",
            players=[trivia_cards.PlayerEntry(n, None, p) for n, p in PLAYERS],
        )  # fmt: skip
        frames.append((frame(podium), CARD_MS))

        # La tabla puede venir en varias tarjetas (las largas se parten): la primera basta
        [standings, *_] = await info._standings_image(
            get_league("PL"), await football.standings("PL")
        )
        frames.append((frame(standings, crop_top=True), CARD_MS + 600))
        team = await info._team_image(await football.team_profile("86"))
        frames.append((frame(team), CARD_MS + 600))
    finally:
        await provider.aclose()
        await images.aclose()

    # Paleta de 256 colores por cuadro, sin tramado (los degradados quedan más limpios)
    gif_frames = [
        f.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for f, _ in frames
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    gif_frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=gif_frames[1:],
        duration=[ms for _, ms in frames],
        loop=0,
        optimize=True,
        disposal=1,
    )
    seconds = sum(ms for _, ms in frames) / 1000
    print(f"{OUTPUT}: {len(frames)} frames, {seconds:.0f} s, {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    asyncio.run(main())
