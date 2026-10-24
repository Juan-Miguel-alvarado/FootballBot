"""Punto de entrada: es lo que corre con `python -m footballbot`.

Pasos: lee la configuración (config.py) -> configura los logs -> crea el bot (bot.py) -> lo conecta
a Discord. `bot.run` se queda corriendo hasta que lo pares con Ctrl+C.
"""

import logging

import discord
from pydantic import ValidationError

from footballbot.bot import FootballBot
from footballbot.config import Settings


def main() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as e:
        # Falta algo en el .env (por ejemplo DISCORD_TOKEN): mostramos qué variables faltan
        # en vez de un traceback largo.
        missing = ", ".join(str(err["loc"][0]).upper() for err in e.errors())
        raise SystemExit(
            f"Invalid or missing settings: {missing}. Copy .env.example to .env."
        ) from None

    # Formato de logs de discord.py (con colores en la terminal), aplicado a todo el bot.
    discord.utils.setup_logging(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    bot = FootballBot(settings)
    # log_handler=None: los logs ya están configurados arriba, que discord.py no lo haga otra vez.
    bot.run(settings.discord_token.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    main()
