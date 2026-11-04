"""Comandos de utilidad: /ping y /help.

Un "cog" es una clase que agrupa slash commands. Cada método con `@app_commands.command`
es un comando; su nombre es el del método y `description` es el texto que se ve en Discord.
Este cog se carga desde bot.py (EXTENSIONS) gracias a la función `setup` del final.
"""

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.bot import ERROR_COLOR, FootballBot
from footballbot.cogs.common import COLOR, MAX_CHOICES, branded
from footballbot.errors import UserFacingError
from footballbot.providers.base import ProviderError


class Admin(commands.Cog):
    """Bot utilities."""

    def __init__(self, bot: FootballBot) -> None:
        self.bot = bot

    @app_commands.command(description="Bot latency and football API status")
    async def ping(self, interaction: discord.Interaction) -> None:
        # defer(): le dice a Discord "estoy en ello" (muestra "thinking..."). Sin esto hay que
        # responder en menos de 3 s, y la API puede tardar más. ephemeral=True: solo lo ve quien
        # usó el comando.
        await interaction.response.defer(ephemeral=True)
        # latency: tiempo de ida y vuelta con Discord, en segundos.
        latency_ms = self.bot.latency * 1000
        # Tres datos en columnas: Discord, la API de fútbol y el autocompletado
        embed = discord.Embed(color=_latency_color(latency_ms))
        embed.add_field(name="Discord", value=f"**{latency_ms:.0f}** ms")
        try:
            health = await self.bot.football.api_status()
        except ProviderError as e:
            embed.title = "Football data is unreachable"
            embed.description = f"-# {e}"
            embed.add_field(name="Football data", value="Down")
            embed.color = ERROR_COLOR
        else:
            embed.title = "All systems normal" if latency_ms < 400 else "Discord is slow right now"
            api = f"**{health.last_latency_ms:.0f}** ms" if health.last_latency_ms else "OK"
            embed.add_field(name="Football data", value=api)
            if health.requests_left is not None:
                quota = f"**{health.requests_left}**/10 this minute"
                embed.add_field(name="API quota", value=quota)
        embed.add_field(name="Teams indexed", value=f"**{self.bot.football.indexed_teams}**")
        branded(embed, self.bot, "Status")
        # Después de un defer se responde con followup.send (no con response.send_message).
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(description="List the bot's commands")
    @app_commands.describe(command="Show details for one command")
    async def help(self, interaction: discord.Interaction, command: str | None = None) -> None:
        # La lista se arma sola a partir de los comandos registrados: si añades un comando,
        # aparece aquí sin tocar nada.
        commands_ = sorted(self._commands(), key=lambda c: c.qualified_name)
        if command:
            # /help <command>: detalle de un comando con sus opciones.
            match = next((c for c in commands_ if c.qualified_name == command.lstrip("/")), None)
            if match is None:
                raise UserFacingError(f"There is no `/{command}` command. See `/help`.")
            # /help <command>: para qué sirve, cómo se escribe y cada opción
            embed = discord.Embed(
                title=f"/{match.qualified_name}", description=match.description, color=COLOR
            )
            embed.add_field(name="Usage", value=f"`{_usage(match)}`", inline=False)
            if match.parameters:
                options = [
                    f"`{p.display_name}`{'' if p.required else ' (optional)'} · {p.description}"
                    for p in match.parameters
                ]
                embed.add_field(name="Options", value="\n".join(options), inline=False)
        else:
            # /help: solo el nombre de cada comando y para qué sirve, por categorías.
            # Las opciones de cada uno están en /help <command> (así ninguna línea se parte).
            embed = discord.Embed(
                title="Commands",
                description="Football info and crest trivia for your server.",
                color=COLOR,
            )
            by_category: dict[str, list[str]] = {}
            for c in commands_:
                category = CATEGORIES.get(type(c.binding).__name__, "Utilities")
                by_category.setdefault(category, []).append(
                    f"`/{c.qualified_name}` {c.description}"
                )
            for category in sorted(by_category, key=_category_order):
                embed.add_field(name=category, value="\n".join(by_category[category]), inline=False)
            embed.set_footer(text="/help <command> shows its options")
        await interaction.response.send_message(
            embed=branded(embed, self.bot, "Help"), ephemeral=True
        )

    @help.autocomplete("command")
    async def _help_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Sugiere nombres de comandos en /help."""
        names = sorted(c.qualified_name for c in self._commands())
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n][
            :MAX_CHOICES
        ]

    def _commands(self) -> list[app_commands.Command]:
        """Todos los slash commands del bot (sin los grupos, que solo contienen comandos)."""
        return [c for c in self.bot.tree.walk_commands() if isinstance(c, app_commands.Command)]


# Nombre de la categoría de /help para cada cog (la clase que define los comandos)
CATEGORIES = {"Info": "Football", "Trivia": "Trivia", "Admin": "Utilities"}


def _category_order(name: str) -> int:
    order = list(CATEGORIES.values())
    return order.index(name) if name in order else len(order)


def _latency_color(ms: float) -> discord.Color:
    """Color del embed de /ping: azul del logo si va rápido, ámbar si normal, rojo si lento."""
    if ms < 150:
        return COLOR
    return discord.Color.from_rgb(212, 167, 44) if ms < 400 else discord.Color.from_rgb(214, 69, 69)


def _usage(command: app_commands.Command) -> str:
    """Cómo se usa un comando: "/matches [league] [date]". <> = obligatorio, [] = opcional."""
    params = [
        f"<{p.display_name}>" if p.required else f"[{p.display_name}]" for p in command.parameters
    ]
    return " ".join([f"/{command.qualified_name}", *params])


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Admin(bot))
