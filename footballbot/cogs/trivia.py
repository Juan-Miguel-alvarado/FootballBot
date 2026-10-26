"""Comandos de trivia: /trivia start, /trivia stop y /leaderboard, más el bucle de cada partida.

Cómo funciona una partida:
1. `/trivia start` valida, crea una GameSession (services/trivia/session.py) y lanza
   `_run_game` como tarea en segundo plano: el comando responde enseguida y el juego sigue solo.
2. Cada ronda (`_play_round`): manda el escudo con el efecto más fuerte y cada STAGE_SECONDS
   edita el mensaje con una imagen más clara. Se corta antes si alguien acierta.
3. Las respuestas llegan por los botones (AnswerView) o por el chat (`on_message`) y van a
   `session.answer(...)`, que decide si es correcta y cuántos puntos da.
4. Al final se guarda todo en la base de datos (storage/repos.py) y se muestra el ranking.

Hay una partida por canal como máximo (`self.games`). Si el bot se reinicia a mitad de partida,
esa partida se pierde; los puntos de partidas terminadas sí quedan guardados.
"""

import asyncio
import contextlib
import io
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.bot import FootballBot
from footballbot.cogs.common import COLOR
from footballbot.errors import UserFacingError
from footballbot.imaging.effects import render_stage
from footballbot.imaging.loader import ImageDownloadError
from footballbot.models import Question, TriviaItem
from footballbot.services.trivia.dataset import TriviaDataset, load_dataset
from footballbot.services.trivia.matching import simplify
from footballbot.services.trivia.modes import DIFFICULTIES, MODES, QuestionPicker, pool_for
from footballbot.services.trivia.session import STAGE_POINTS, AnswerMode, GameSession, Outcome
from footballbot.storage import repos

log = logging.getLogger(__name__)

# Tiempos, en segundos. Discord limita las ediciones de un mensaje: no bajar de ~4 s por etapa.
START_DELAY = 3  # entre /trivia start y la primera ronda
STAGE_SECONDS = 5  # cada etapa de la imagen
BETWEEN_ROUNDS = 4  # mostrando la respuesta antes de la siguiente ronda

DEFAULT_ROUNDS = 10
MAX_ROUNDS = 20
# Si un escudo no se puede bajar, se prueba con otra pregunta hasta este número de veces
MAX_IMAGE_ATTEMPTS = 3

MEDALS = ("🥇", "🥈", "🥉")

_MODE_CHOICES = [app_commands.Choice(name=m.title, value=m.key) for m in MODES.values()]


class Trivia(commands.Cog):
    """Crest trivia games."""

    # Grupo de comandos: /trivia start y /trivia stop. guild_only: no funciona por mensaje directo.
    trivia = app_commands.Group(name="trivia", description="Crest trivia games", guild_only=True)

    def __init__(self, bot: FootballBot) -> None:
        self.bot = bot
        self.dataset: TriviaDataset | None = None
        self.games: dict[int, GameSession] = {}  # id del canal -> partida en curso
        # Guardamos las tareas para que Python no las borre mientras corren
        self._tasks: set[asyncio.Task[None]] = set()

    async def cog_load(self) -> None:
        # Leer los JSON del dataset es rápido, pero es disco: fuera del bucle del bot.
        self.dataset = await asyncio.to_thread(load_dataset)

    async def cog_unload(self) -> None:
        for session in self.games.values():
            session.stop()
        for task in self._tasks:
            task.cancel()

    # --- comandos --------------------------------------------------------------------------

    # /trivia start <mode> [difficulty] [rounds] [answers]
    @trivia.command(name="start", description="Start a crest trivia game in this channel")
    @app_commands.describe(
        mode="What to guess",
        difficulty="easy: top 5 leagues (default) · medium: + more leagues · hard: everything",
        rounds=f"How many rounds (default {DEFAULT_ROUNDS})",
        answers="Answer with buttons (default) or by typing in the chat",
    )
    @app_commands.choices(
        mode=_MODE_CHOICES,
        difficulty=[app_commands.Choice(name=d.title(), value=d) for d in DIFFICULTIES],
        answers=[
            app_commands.Choice(name="Buttons", value=AnswerMode.BUTTONS.value),
            app_commands.Choice(name="Typed", value=AnswerMode.TYPED.value),
        ],
    )
    async def start(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        difficulty: app_commands.Choice[str] | None = None,
        rounds: app_commands.Range[int, 1, MAX_ROUNDS] = DEFAULT_ROUNDS,
        answers: app_commands.Choice[str] | None = None,
    ) -> None:
        channel = interaction.channel
        guild = interaction.guild
        if not isinstance(channel, discord.abc.Messageable) or guild is None or channel is None:
            raise UserFacingError("Trivia only works in a server channel.")
        if channel.id in self.games:
            raise UserFacingError(
                "There is already a game in this channel. Use `/trivia stop` to end it."
            )
        answer_mode = AnswerMode(answers.value if answers else AnswerMode.BUTTONS)
        if answer_mode is AnswerMode.TYPED and not self.bot.settings.trivia_typed_answers:
            raise UserFacingError(
                "Typed answers are not turned on for this bot yet, so use buttons for now. "
                "(An admin has to enable the Message Content intent.)"
            )
        _check_permissions(channel, guild.me)
        assert self.dataset is not None  # se carga en cog_load

        game_mode = MODES[mode.value]
        level = difficulty.value if difficulty else "easy"
        picker = QuestionPicker(pool_for(game_mode, self.dataset, level))
        session = GameSession(
            guild_id=guild.id,
            channel_id=channel.id,
            started_by=interaction.user.id,
            mode=game_mode,
            difficulty=level,
            # Hay modos con pocas respuestas posibles (13 ligas): no más rondas que preguntas
            rounds=min(rounds, picker.remaining),
            answer_mode=answer_mode,
        )
        self.games[channel.id] = session
        await interaction.response.send_message(embed=_start_embed(session, interaction.user))

        task = asyncio.create_task(self._run_game(session, picker, channel))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # /trivia stop
    @trivia.command(name="stop", description="Stop the trivia game in this channel")
    async def stop(self, interaction: discord.Interaction) -> None:
        session = self.games.get(interaction.channel_id or 0)
        if session is None:
            raise UserFacingError("There is no trivia game in this channel.")
        # Puede pararla quien la empezó o alguien con permiso de moderar mensajes
        if (
            interaction.user.id != session.started_by
            and not interaction.permissions.manage_messages
        ):
            raise UserFacingError("Only whoever started the game or a moderator can stop it.")
        session.stop()
        await interaction.response.send_message("Stopping the game...")

    # /leaderboard [mode]
    @app_commands.command(description="Trivia points ranking for this server")
    @app_commands.guild_only()
    @app_commands.describe(mode="Only one trivia mode (default: all modes)")
    @app_commands.choices(mode=_MODE_CHOICES)
    async def leaderboard(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None
    ) -> None:
        assert interaction.guild_id is not None  # guild_only
        rows = await repos.leaderboard(
            self.bot.db, interaction.guild_id, mode.value if mode else None
        )
        title = "🏆 Trivia leaderboard"
        if mode:
            title += f" · {MODES[mode.value].title}"
        embed = discord.Embed(title=title, color=COLOR)
        if rows:
            # Las menciones dentro de un embed (<@id>) se ven como nombre pero no notifican
            embed.description = "\n".join(
                f"{_rank_label(i)} <@{r.user_id}> · **{r.points:,}** pts · "
                f"{r.correct} correct · {r.played} {'game' if r.played == 1 else 'games'}"
                for i, r in enumerate(rows)
            )
        else:
            embed.description = "No games yet. Start one with `/trivia start`."
        await interaction.response.send_message(embed=embed)

    # --- respuestas escritas ---------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Solo llega el texto si TRIVIA_TYPED_ANSWERS=true (intent message_content)
        if message.author.bot or message.guild is None:
            return
        session = self.games.get(message.channel.id)
        if session is None or session.answer_mode is not AnswerMode.TYPED:
            return
        outcome, _ = session.answer(message.author.id, text=message.content)
        if outcome is Outcome.CORRECT:
            # Sin permiso de reaccionar no pasa nada: el mensaje de la ronda ya dice quién ganó
            with contextlib.suppress(discord.HTTPException):
                await message.add_reaction("✅")

    # --- la partida ------------------------------------------------------------------------

    async def _run_game(
        self, session: GameSession, picker: QuestionPicker, channel: discord.abc.Messageable
    ) -> None:
        try:
            await asyncio.sleep(START_DELAY)
            while not session.finished:
                question, crest = await self._next_question(picker)
                await self._play_round(session, question, crest, channel)
                if not session.finished:
                    await asyncio.sleep(BETWEEN_ROUNDS)
        except Exception as e:
            # Un error no debe dejar el canal "ocupado" para siempre ni perder los puntos
            log.exception("Trivia game in channel %s crashed", session.channel_id)
            await self.bot.report_error(f"Trivia game in <#{session.channel_id}>", e)
            await _send_quietly(channel, "Something went wrong and the game had to stop.")
        finally:
            self.games.pop(session.channel_id, None)
        await self._finish_game(session, channel)

    async def _next_question(self, picker: QuestionPicker) -> tuple[Question, bytes]:
        """La siguiente pregunta con su escudo ya descargado. Salta escudos que no bajan."""
        for _ in range(MAX_IMAGE_ATTEMPTS):
            question = picker.next()
            try:
                return question, await self.bot.images.get(question.answer.image_url)
            except ImageDownloadError as e:
                log.warning("Skipping %s: %s", question.answer.name, e)
        raise RuntimeError("could not download the images for the trivia questions")

    async def _play_round(
        self,
        session: GameSession,
        question: Question,
        crest: bytes,
        channel: discord.abc.Messageable,
    ) -> None:
        session.start_round(question)
        view = AnswerView(session, question) if session.answer_mode is AnswerMode.BUTTONS else None

        message: discord.Message | None = None
        while True:
            png = await asyncio.to_thread(
                render_stage, crest, session.mode.effect, session.mode.levels[session.stage]
            )
            file = _image_file(png, session)
            embed = _round_embed(session)
            if message is None:
                kwargs = {"view": view} if view else {}
                message = await channel.send(embed=embed, file=file, **kwargs)
            else:
                await _edit_quietly(message, embed=embed, attachments=[file])
            try:
                # Espera a que alguien acierte (o se pare el juego) como mucho STAGE_SECONDS
                await asyncio.wait_for(session.round_over.wait(), timeout=STAGE_SECONDS)
                break
            except TimeoutError:
                if not session.next_stage():
                    break  # se acabaron las etapas y nadie acertó

        if session.round_open:
            session.close_round()
        png = await asyncio.to_thread(render_stage, crest, session.mode.effect, None)
        kwargs = {"view": view.reveal()} if view else {}
        await _edit_quietly(
            message,
            embed=_reveal_embed(session),
            attachments=[_image_file(png, session, "answer")],
            **kwargs,
        )
        if view:
            view.stop()

    async def _finish_game(self, session: GameSession, channel: discord.abc.Messageable) -> None:
        if session.answers:
            try:
                await repos.save_game(self.bot.db, session.result())
            except Exception as e:
                log.exception("Could not save trivia game")
                await self.bot.report_error("Saving a trivia game", e)
        await _send_quietly(channel, embed=_summary_embed(session))


class AnswerView(discord.ui.View):
    """Los 4 botones de una ronda. Cada clic llama a `session.answer` y responde solo a quien
    hizo clic (ephemeral), para no llenar el chat."""

    def __init__(self, session: GameSession, question: Question) -> None:
        super().__init__(timeout=None)  # el bucle de la ronda decide cuándo se acaba
        self.session = session
        self.question = question
        self._buttons: list[tuple[discord.ui.Button[AnswerView], TriviaItem]] = []
        for option in question.options:
            button: discord.ui.Button[AnswerView] = discord.ui.Button(
                label=option.name[:80], style=discord.ButtonStyle.secondary
            )
            button.callback = self._callback_for(option)
            self.add_item(button)
            self._buttons.append((button, option))

    def _callback_for(
        self, option: TriviaItem
    ) -> Callable[[discord.Interaction], Coroutine[Any, Any, None]]:
        async def callback(interaction: discord.Interaction) -> None:
            outcome, points = self.session.answer(interaction.user.id, choice_id=option.id)
            await interaction.response.send_message(_outcome_text(outcome, points), ephemeral=True)

        return callback

    def reveal(self) -> "AnswerView":
        """Desactiva los botones y pinta de verde la respuesta correcta."""
        for button, option in self._buttons:
            button.disabled = True
            if option.id == self.question.answer.id:
                button.style = discord.ButtonStyle.success
        return self


# --- ayudantes -------------------------------------------------------------------------------


def _check_permissions(channel: discord.abc.Messageable, me: discord.Member) -> None:
    """Sin estos permisos el bot no puede mandar la imagen de cada ronda."""
    if not isinstance(channel, discord.abc.GuildChannel | discord.Thread):
        return
    perms = channel.permissions_for(me)
    can_send = (
        perms.send_messages_in_threads
        if isinstance(channel, discord.Thread)
        else (perms.send_messages)
    )
    needed = {"Send Messages": can_send, "Embed Links": perms.embed_links,
              "Attach Files": perms.attach_files}  # fmt: skip
    missing = [name for name, ok in needed.items() if not ok]
    if missing:
        raise UserFacingError(f"I need these permissions in this channel: {', '.join(missing)}.")


async def _send_quietly(
    channel: discord.abc.Messageable, content: str | None = None, **kwargs: Any
) -> discord.Message | None:
    """Envía un mensaje; si Discord falla (sin permisos, canal borrado), solo lo anota."""
    try:
        return await channel.send(content, **kwargs)
    except discord.HTTPException:
        log.warning("Could not send a trivia message", exc_info=True)
        return None


async def _edit_quietly(message: discord.Message, **kwargs: Any) -> None:
    """Edita un mensaje; si lo borraron o Discord falla, la partida sigue igual."""
    try:
        await message.edit(**kwargs)
    except discord.HTTPException:
        log.warning("Could not edit a trivia message", exc_info=True)


def _image_file(png: bytes, session: GameSession, suffix: str | None = None) -> discord.File:
    # Un nombre distinto por etapa: si se repite, Discord a veces muestra la imagen anterior
    name = f"trivia-{session.round}-{suffix or session.stage}.png"
    return discord.File(io.BytesIO(png), filename=name)


def _rank_label(index: int) -> str:
    return MEDALS[index] if index < len(MEDALS) else f"`{index + 1}.`"


def _outcome_text(outcome: Outcome, points: int) -> str:
    match outcome:
        case Outcome.CORRECT:
            return f"✅ Correct! +{points} points"
        case Outcome.WRONG:
            return "❌ Wrong. You're out for this round."
        case Outcome.ALREADY_TRIED:
            return "You already answered this round."
        case Outcome.CLOSED:
            return "Too late, this round is over."


def _start_embed(session: GameSession, user: discord.abc.User) -> discord.Embed:
    how = "buttons" if session.answer_mode is AnswerMode.BUTTONS else "typing in the chat"
    points = " / ".join(str(p) for p in STAGE_POINTS)
    embed = discord.Embed(
        title=f"Trivia · {session.mode.title}",
        description=(
            f"{user.mention} started a game: **{session.total_rounds}** rounds, "
            f"**{session.difficulty}** difficulty, answers by **{how}**.\n\n"
            f"The image gets clearer every {STAGE_SECONDS} seconds. "
            f"Answer early for more points ({points}), plus a bonus for winning rounds in a row."
            f"\n\nFirst round in {START_DELAY} seconds..."
        ),
        color=COLOR,
    )
    embed.set_footer(text="/trivia stop ends the game")
    return embed


def _round_embed(session: GameSession) -> discord.Embed:
    how = (
        "Pick a button."
        if session.answer_mode is AnswerMode.BUTTONS
        else "Type the answer in the chat."
    )
    embed = discord.Embed(
        title=f"Round {session.round}/{session.total_rounds} · {session.mode.prompt}",
        description=how,
        color=COLOR,
    )
    embed.set_image(url=f"attachment://trivia-{session.round}-{session.stage}.png")
    embed.set_footer(
        text=f"Stage {session.stage + 1}/{session.stages} · "
        f"{STAGE_POINTS[session.stage]} points now"
    )
    return embed


def _reveal_embed(session: GameSession) -> discord.Embed:
    assert session.question is not None
    answer = session.question.answer
    name = answer.name
    # El nombre completo solo se añade si dice algo más: "Brentford (Brentford FC)" no aporta
    if simplify(answer.name) not in simplify(answer.full_name):
        name += f" ({answer.full_name})"
    if session.winner is not None:
        # La última respuesta guardada es la que ganó la ronda
        points = session.answers[-1].points
        embed = discord.Embed(
            title=f"✅ {name}",
            description=f"<@{session.winner}> got it! **+{points}** points",
            color=discord.Color.green(),
        )
    else:
        reason = "Game stopped." if session.stopped else "⏱️ Nobody got it."
        embed = discord.Embed(title=name, description=reason, color=discord.Color.light_grey())
    embed.set_image(url=f"attachment://trivia-{session.round}-answer.png")
    top = session.ranking()[:3]
    if top:
        embed.add_field(
            name="Scores",
            value="\n".join(
                f"{_rank_label(i)} <@{p.user_id}> · {p.points}" for i, p in enumerate(top)
            ),
        )
    embed.set_footer(text=f"Round {session.round}/{session.total_rounds}")
    return embed


def _summary_embed(session: GameSession) -> discord.Embed:
    embed = discord.Embed(title="🏁 Game over", color=COLOR)
    ranking = session.ranking()
    if ranking:
        embed.description = "\n".join(
            f"{_rank_label(i)} <@{p.user_id}> · **{p.points}** pts · {p.correct} correct · "
            f"best streak {p.best_streak}"
            for i, p in enumerate(ranking)
        )
    else:
        embed.description = "Nobody scored this time."
    embed.set_footer(text=f"{session.round} rounds played · /leaderboard for the server ranking")
    return embed


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Trivia(bot))
