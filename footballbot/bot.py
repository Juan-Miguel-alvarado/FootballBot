"""El bot: se conecta a Discord, carga los comandos y maneja los errores.

Quién lo usa: `__main__.py` crea `FootballBot(settings)` y llama `bot.run(...)`.

Qué pasa al arrancar (en orden):
1. `__init__`: crea el cliente de la API (provider), el FootballService, la base de datos
   y el descargador de imágenes. Todos los cogs los usan a través de `self.bot`.
2. `setup_hook`: abre la base de datos (y aplica migraciones), carga los cogs de EXTENSIONS
   (cada cog registra sus slash commands) y los sincroniza con Discord para que aparezcan
   al escribir "/".
3. `on_ready`: ya está conectado; lo anota en el log.

Para añadir un archivo de comandos nuevo (un cog): créalo en `cogs/`, con una función
`setup(bot)` al final (copia la de cogs/admin.py), y añade su ruta a EXTENSIONS.
"""

import logging
import sys
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.config import Settings
from footballbot.errors import UserFacingError
from footballbot.imaging.loader import ImageLoader
from footballbot.providers.base import (
    NotFoundError,
    NotInPlanError,
    ProviderError,
    RateLimitedError,
)
from footballbot.providers.football_data import FootballDataProvider
from footballbot.services.football import FootballService
from footballbot.storage.db import Database

log = logging.getLogger(__name__)

# Los cogs que se cargan al arrancar (módulos de footballbot/cogs/).
EXTENSIONS = (
    "footballbot.cogs.admin",
    "footballbot.cogs.info",
    "footballbot.cogs.trivia",
)

# Discord messages are capped at 2000 characters
MAX_TRACEBACK = 1800


class FootballBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        # Slash commands only need guilds. Typed trivia answers add message_content.
        # (Los "intents" son los tipos de eventos que Discord nos manda. message_content es
        # privilegiado: hay que activarlo en el Developer Portal antes de poner
        # TRIVIA_TYPED_ANSWERS=true, o Discord rechaza la conexión.)
        intents = discord.Intents(guilds=True, guild_messages=True)
        intents.message_content = settings.trivia_typed_answers
        # command_prefix es obligatorio en commands.Bot, pero no usamos comandos con prefijo
        # (tipo "!help"): todo son slash commands. help_command=None quita el "!help" automático.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.settings = settings
        # Estos objetos viven mientras el bot está encendido y los comparten todos los cogs.
        self.provider = FootballDataProvider(settings.football_data_key.get_secret_value())
        self.football = FootballService(self.provider, settings.tz)
        self.db = Database(settings.database_url)
        self.images = ImageLoader()
        # Todos los errores de slash commands pasan por on_app_command_error (más abajo).
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        """discord.py lo llama una vez, antes de conectarse. Aquí se cargan los cogs."""
        await self.db.connect()
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        await self.sync_commands()

    async def sync_commands(self) -> None:
        """Le envía a Discord la lista de slash commands para que salgan en el menú de "/"."""
        guild_id = self.settings.discord_dev_guild_id
        if guild_id:
            # Guild sync is instant; global sync can take a while to show up
            # copy_global_to: copia los comandos al servidor de pruebas y los sincroniza solo ahí.
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), guild_id)
        else:
            # Sin servidor de pruebas: sincroniza en todos los servidores (producción).
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s) in %d guilds", self.user, self.user.id, len(self.guilds))

    async def on_message(self, message: discord.Message) -> None:
        # No hacemos nada a propósito. Por defecto discord.py intenta leer cada mensaje que
        # menciona al bot como un comando con prefijo ("@bot help"); como no usamos esos
        # comandos, solo llenaba el log de errores "CommandNotFound". Los cogs que necesitan
        # mensajes (la trivia con respuestas escritas) usan su propio listener y siguen
        # funcionando.
        return

    async def close(self) -> None:
        """Al apagar el bot (Ctrl+C) cerramos también la API, las imágenes y la base de datos."""
        await self.provider.aclose()
        await self.images.aclose()
        await self.db.close()
        await super().close()

    # --- errors ----------------------------------------------------------------------------

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Cualquier excepción en un slash command termina aquí.

        Se le responde al usuario con un mensaje corto (solo él lo ve). Si es un bug de
        verdad (un error que no esperábamos), además se manda el traceback al canal de errores.
        La tabla de qué error da qué mensaje está en ARCHITECTURE.md ("Error handling").
        """
        # discord.py envuelve nuestra excepción en CommandInvokeError: sacamos la original.
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        report = False
        match original:
            case UserFacingError():
                # El usuario se equivocó (fecha mal escrita...): se le muestra el mensaje tal cual.
                message = str(original)
            case NotInPlanError():
                # Va antes que NotFoundError porque es un caso particular de él
                message = (
                    "That isn't included in the free football data plan we use "
                    "(national teams, for example). Try a club instead."
                )
            case NotFoundError():
                message = "I couldn't find that. Check the name or pick one from the suggestions."
            case RateLimitedError():
                message = "The football API is busy right now. Try again in a minute."
            case ProviderError():
                message = "The football data service is not responding. Try again in a moment."
                log.warning("Provider error in /%s: %s", _command_name(interaction), original)
            case app_commands.CheckFailure():
                message = "You can't use this command here."
            case _:
                # Cualquier otra cosa es un bug nuestro.
                message = "Something went wrong. The error has been reported."
                report = True

        await self._reply_error(interaction, message)
        if report:
            log.error(
                "Error in /%s",
                _command_name(interaction),
                exc_info=(type(original), original, original.__traceback__),
            )
            context = (
                f"**/{_command_name(interaction)}** by {interaction.user} "
                f"in {interaction.guild or 'DMs'}"
            )
            await self.report_error(context, original)

    async def on_error(self, event_method: str, /, *args: object, **kwargs: object) -> None:
        """Errores fuera de los slash commands (por ejemplo en un evento como on_ready)."""
        log.exception("Error in event %s", event_method)
        error = sys.exc_info()[1]
        if error is not None:
            await self.report_error(f"Event **{event_method}**", error)

    async def report_error(self, context: str, error: BaseException) -> None:
        """Posts the traceback to the errors channel, if one is configured.

        El canal se configura con DISCORD_ERRORS_CHANNEL_ID en el .env. Si no está, no hace nada
        (el error igual queda en el log de la terminal).
        """
        channel_id = self.settings.discord_errors_channel_id
        if not channel_id:
            return
        # Nos quedamos con el final del traceback, que es donde está la línea que falló.
        tb = "".join(traceback.format_exception(error))[-MAX_TRACEBACK:]
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if isinstance(channel, discord.abc.Messageable):
                await channel.send(f"{context}\n```py\n{tb}\n```")
        except discord.HTTPException:
            log.exception("Could not send the error report to channel %s", channel_id)

    async def _reply_error(self, interaction: discord.Interaction, message: str) -> None:
        """Responde el error al usuario. ephemeral=True: solo él lo ve."""
        try:
            # Si el comando ya hizo defer() (el "FootballTrivia is thinking..."), hay que
            # responder con followup; si no, con response.send_message.
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            # La interacción pudo vencer (Discord da 15 minutos); no hay a quién responder.
            log.warning("Could not send the error message for /%s", _command_name(interaction))


def _command_name(interaction: discord.Interaction) -> str:
    return interaction.command.qualified_name if interaction.command else "?"
