"""Tests de los mensajes de error que ve el usuario (bot.py:on_app_command_error).

Se crea el bot con claves falsas (no se conecta a Discord) y una interacción falsa que solo
guarda lo que el bot le respondería al usuario.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord import app_commands

from footballbot.bot import FootballBot
from footballbot.config import Settings
from footballbot.errors import UserFacingError
from footballbot.providers.base import NotFoundError, NotInPlanError


@pytest.fixture
async def bot(tmp_path):
    settings = Settings(
        discord_token="fake",
        football_data_key="fake",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        discord_errors_channel_id=None,
        trivia_typed_answers=False,
    )
    bot = FootballBot(settings)
    yield bot
    await bot.provider.aclose()
    await bot.images.aclose()


def fake_interaction() -> SimpleNamespace:
    response = SimpleNamespace(is_done=lambda: False, send_message=AsyncMock())
    return SimpleNamespace(
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        command=SimpleNamespace(qualified_name="team"),
        user="tester",
        guild="server",
    )


async def reply_for(bot: FootballBot, error: Exception) -> str:
    interaction = fake_interaction()
    wrapped = app_commands.CommandInvokeError(MagicMock(), error)
    await bot.on_app_command_error(interaction, wrapped)
    args, kwargs = interaction.response.send_message.call_args
    assert kwargs["ephemeral"] is True  # solo lo ve quien usó el comando
    return args[0]


async def test_not_in_plan_message(bot: FootballBot) -> None:
    message = await reply_for(bot, NotInPlanError("/teams/762 is not included in the free plan"))
    assert "free football data plan" in message
    assert "national teams" in message


async def test_not_found_message(bot: FootballBot) -> None:
    assert "couldn't find" in await reply_for(bot, NotFoundError("/teams/1 not found"))


async def test_user_facing_message_is_shown_as_is(bot: FootballBot) -> None:
    assert await reply_for(bot, UserFacingError("Bad date")) == "Bad date"
