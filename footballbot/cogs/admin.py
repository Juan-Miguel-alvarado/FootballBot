"""Comandos de utilidad: /ping y /help.

Un "cog" es una clase que agrupa slash commands. Cada método con `@app_commands.command`
es un comando; su nombre es el del método y `description` es el texto que se ve en Discord.
Este cog se carga desde bot.py (EXTENSIONS) gracias a la función `setup` del final.
"""

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.bot import FootballBot
from footballbot.cogs.common import COLOR, MAX_CHOICES
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
        embed = discord.Embed(title="🏓 Pong", color=COLOR)
        # latency: tiempo de ida y vuelta con Discord, en segundos.
        embed.add_field(name="Discord", value=f"{self.bot.latency * 1000:.0f} ms")
        try:
            health = await self.bot.football.api_status()
        except ProviderError as e:
            embed.add_field(name="football-data.org", value=f"❌ {e}", inline=False)
        else:
            parts = ["✅ OK"]
            if health.last_latency_ms is not None:
                parts.append(f"{health.last_latency_ms:.0f} ms")
            if health.requests_left is not None:
                parts.append(f"{health.requests_left} requests left this minute")
            embed.add_field(name=health.name, value=" · ".join(parts), inline=False)
        embed.add_field(name="Teams indexed", value=str(self.bot.football.indexed_teams))
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
                await interaction.response.send_message(
                    f"There is no `/{command}` command.", ephemeral=True
                )
                return
            embed = discord.Embed(title=_usage(match), description=match.description, color=COLOR)
            for param in match.parameters:
                embed.add_field(name=param.display_name, value=param.description, inline=False)
        else:
            # /help: lista de todos los comandos.
            lines = [f"`{_usage(c)}` · {c.description}" for c in commands_]
            embed = discord.Embed(title="Commands", description="\n".join(lines), color=COLOR)
            embed.set_footer(text="<required> [optional] · /help <command> for details")
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


def _usage(command: app_commands.Command) -> str:
    """Cómo se usa un comando: "/matches [league] [date]". <> = obligatorio, [] = opcional."""
    params = [
        f"<{p.display_name}>" if p.required else f"[{p.display_name}]" for p in command.parameters
    ]
    return " ".join([f"/{command.qualified_name}", *params])


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Admin(bot))
