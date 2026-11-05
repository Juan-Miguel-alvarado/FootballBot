"""Comandos de utilidad: /ping y /help.

Un "cog" es una clase que agrupa slash commands. Cada método con `@app_commands.command`
es un comando; su nombre es el del método y `description` es el texto que se ve en Discord.
Este cog se carga desde bot.py (EXTENSIONS) gracias a la función `setup` del final.
"""

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.bot import ERROR_COLOR, FootballBot
from footballbot.cogs.common import COLOR, MAX_CHOICES, command_mention
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
        # Un renglón por servicio: qué es, cómo va y su número
        # Un renglón por servicio, con un punto de color: verde bien, amarillo lento, rojo caído
        lines = [
            f"{_dot(latency_ms)} **Bot to Discord** · {_speed(latency_ms)} ({latency_ms:.0f} ms)"
        ]
        embed = discord.Embed(color=_latency_color(latency_ms))
        try:
            health = await self.bot.football.api_status()
        except ProviderError:
            embed.title = "Football data is unreachable"
            lines.append("🔴 **Football data** · down, match commands won't work for now")
            embed.color = ERROR_COLOR
        else:
            embed.title = "All systems normal" if latency_ms < 400 else "Discord is slow right now"
            busy = health.requests_left is not None and health.requests_left <= 2
            if busy:
                # Pocas peticiones libres este minuto: se avisa en palabras, no con el número.
                # El título y el color siguen al peor de los dos estados
                lines.append("🟡 **Football data** · busy, commands may take a few seconds")
                if latency_ms < 400:
                    embed.title = "Football data is busy"
                    embed.color = discord.Color.from_rgb(212, 167, 44)
            else:
                lines.append("🟢 **Football data** · online")
        embed.description = "\n".join(lines)
        # Después de un defer se responde con followup.send (no con response.send_message).
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(description="List the bot's commands")
    @app_commands.describe(command="Show details for one command")
    async def help(self, interaction: discord.Interaction, command: str | None = None) -> None:
        # La lista se arma sola a partir de los comandos registrados: si añades un comando,
        # aparece aquí sin tocar nada.
        # Orden alfabético, salvo /trivia start, que va primero: es lo principal del bot
        commands_ = sorted(
            self._commands(), key=lambda c: (c.qualified_name != "trivia start", c.qualified_name)
        )
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
                # Una opción por renglón; debajo, en pequeño, los valores que acepta
                options = []
                for p in match.parameters:
                    line = f"**{p.display_name}**{'' if p.required else ' (optional)'}"
                    line += f" · {p.description}"
                    # (si la descripción ya nombra los valores, no se repiten)
                    described = any(c.name.lower() in p.description.lower() for c in p.choices)
                    if p.choices and not described:
                        line += "\nChoices: " + ", ".join(f"`{c.name}`" for c in p.choices)
                    options.append(line)
                embed.add_field(name="Options", value="\n".join(options), inline=False)
            embed.add_field(name="Example", value=f"`{_example(match)}`", inline=False)
        else:
            # /help: solo el nombre de cada comando y para qué sirve, por categorías.
            # Las opciones de cada uno están en /help <command> (así ninguna línea se parte).
            embed = discord.Embed(
                title="Commands",
                description=(
                    f"Start here: {command_mention(self.bot, 'trivia start')} to guess clubs "
                    "from their crests. The football commands show matches, tables and teams.\n"
                    f"Tip: {command_mention(self.bot, 'help')} with a command name shows its "
                    "options."
                ),
                color=COLOR,
            )
            by_category: dict[str, list[str]] = {}
            for c in commands_:
                category = CATEGORIES.get(type(c.binding).__name__, "Utilities")
                by_category.setdefault(category, []).append(
                    f"{command_mention(self.bot, c.qualified_name)} · {c.description}"
                )
            for category in sorted(by_category, key=_category_order):
                embed.add_field(name=category, value="\n".join(by_category[category]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
CATEGORIES = {"Trivia": "Trivia", "Info": "Football", "Admin": "Utilities"}


def _category_order(name: str) -> int:
    order = list(CATEGORIES.values())
    return order.index(name) if name in order else len(order)


def _latency_color(ms: float) -> discord.Color:
    """Color del embed de /ping, el mismo que el punto: verde si va rápido, ámbar, rojo."""
    if ms < 150:
        return discord.Color.from_rgb(35, 165, 90)
    return discord.Color.from_rgb(212, 167, 44) if ms < 400 else discord.Color.from_rgb(214, 69, 69)


def _dot(ms: float) -> str:
    """El punto de color de la latencia (los mismos cortes que el color del embed)."""
    return "🟢" if ms < 150 else "🟡" if ms < 400 else "🔴"


def _speed(ms: float) -> str:
    """ "fast", "normal" o "slow" para la latencia de Discord (los mismos cortes que el color)."""
    return "fast" if ms < 150 else "normal" if ms < 400 else "slow"


# Valores de ejemplo para /help <command> cuando la opción no tiene una lista fija
_EXAMPLE_VALUES = {"league": "PL", "team": "Real Madrid", "date": "tomorrow", "command": "matches"}


def _example(command: app_commands.Command) -> str:
    """Un ejemplo listo para copiar: "/trivia start mode:crest rounds:5"."""
    parts = [f"/{command.qualified_name}"]
    for p in command.parameters:
        # Con opciones fijas, el nombre que ve el usuario en la lista ("Pixelated crest")
        value = p.choices[0].name if p.choices else _EXAMPLE_VALUES.get(p.display_name)
        if value is None and p.type is discord.AppCommandOptionType.integer:
            value = 5
        if value is not None and (p.required or len(parts) < 3):
            parts.append(f"{p.display_name}:{value}")
    return " ".join(parts)


def _usage(command: app_commands.Command) -> str:
    """Cómo se usa un comando: "/matches [league] [date]". <> = obligatorio, [] = opcional."""
    params = [
        f"<{p.display_name}>" if p.required else f"[{p.display_name}]" for p in command.parameters
    ]
    return " ".join([f"/{command.qualified_name}", *params])


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Admin(bot))
