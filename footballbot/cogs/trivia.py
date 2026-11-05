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
import zlib
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from footballbot.bot import FootballBot
from footballbot.cogs.common import COLOR, LOGO_URL, command_mention, logo_file, timestamp
from footballbot.errors import UserFacingError
from footballbot.imaging import trivia_cards
from footballbot.imaging.effects import render_stage
from footballbot.imaging.loader import ImageDownloadError
from footballbot.models import PlayerScore, Question, TriviaItem
from footballbot.services.trivia.dataset import TriviaDataset, load_dataset
from footballbot.services.trivia.modes import (
    DIFFICULTIES,
    MODES,
    Mode,
    QuestionPicker,
    make_picker,
)
from footballbot.services.trivia.session import (
    HINT_COST,
    STAGE_POINTS,
    STREAK_BONUS,
    AnswerMode,
    GameSession,
    Outcome,
)
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


_MODE_CHOICES = [app_commands.Choice(name=m.title, value=m.key) for m in MODES.values()]


class Trivia(commands.Cog):
    """Crest trivia games."""

    # Grupo de comandos: /trivia start y /trivia stop. guild_only: no funciona por mensaje directo.
    trivia = app_commands.Group(name="trivia", description="Crest trivia games", guild_only=True)

    def __init__(self, bot: FootballBot) -> None:
        self.bot = bot
        self.dataset: TriviaDataset | None = None
        self.games: dict[int, GameSession] = {}  # id del canal -> partida en curso
        # id del canal -> {id de usuario: usuario} de quienes respondieron en esa partida.
        # Sirve para poner nombres y avatares en la respuesta y en el podio.
        self.players: dict[int, dict[int, discord.abc.User]] = {}
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
        # Lo que ya salió en este servidor, para no repetir escudos entre partidas (issue #9)
        seen = await repos.last_seen(self.bot.db, guild.id)
        picker = make_picker(game_mode, self.dataset, level, last_seen=seen)
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
        self.players[channel.id] = {}
        await interaction.response.send_message(
            embed=_start_embed(session, interaction.user, self.bot), file=logo_file()
        )

        task = asyncio.create_task(self._run_game(session, picker, channel))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # /trivia hint
    @trivia.command(name="hint", description="Get a hint for this round (you score less)")
    async def hint(self, interaction: discord.Interaction) -> None:
        session = self.games.get(interaction.channel_id or 0)
        if session is None:
            raise UserFacingError("There is no trivia game in this channel.")
        text = session.hint(interaction.user.id)
        if text is None:
            raise UserFacingError("Wait for the next round to start.")
        await interaction.response.send_message(
            f"**Hint:** {text}\n-# Each hint takes {HINT_COST} points off what you win this round.",
            ephemeral=True,
        )

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
        assert interaction.guild is not None  # guild_only
        # Bajar los avatares tarda un poco: "thinking..." mientras tanto
        await interaction.response.defer()
        rows = await repos.leaderboard(
            self.bot.db, interaction.guild.id, mode.value if mode else None
        )
        title = "Trivia leaderboard"
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
            await interaction.followup.send(embed=embed)
            return

        # Tarjeta con avatares (issue #11); si falla, queda el texto de arriba
        file = None
        try:
            people = await asyncio.gather(
                *(self._resolve_user(interaction.guild, r.user_id) for r in rows)
            )
            players = [
                trivia_cards.PlayerEntry(
                    name=name,
                    avatar=picture,
                    points=r.points,
                    detail=f"{r.correct} correct · {r.played} "
                    f"{'game' if r.played == 1 else 'games'} · best streak {r.best_streak}",
                )
                for r, (name, picture) in zip(rows, people, strict=True)
            ]
            subtitle = f"{MODES[mode.value].title if mode else 'All modes'} · "
            subtitle += interaction.guild.name
            png = await asyncio.to_thread(
                trivia_cards.leaderboard_card,
                title="Trivia leaderboard",
                subtitle=subtitle,
                players=players,
            )
            file = discord.File(io.BytesIO(png), filename="leaderboard.png")
        except Exception:
            log.exception("Could not draw the leaderboard card")
        if file is None:
            await interaction.followup.send(embed=embed)
            return
        # La tarjeta ya tiene la lista: el texto solo dice dónde está quien lo pidió
        await interaction.followup.send(_your_rank(rows, players, interaction.user.id), file=file)

    async def _resolve_user(self, guild: discord.Guild, user_id: int) -> tuple[str, bytes | None]:
        """Nombre y avatar de un jugador (aunque ya no esté en el servidor)."""
        user: discord.abc.User | None = guild.get_member(user_id) or self.bot.get_user(user_id)
        if user is None:
            try:
                user = await guild.fetch_member(user_id)
            except discord.HTTPException:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.HTTPException:
                    return "Unknown player", None
        return user.display_name, await _avatar_bytes(user)

    # --- respuestas escritas ---------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Solo llega el texto si TRIVIA_TYPED_ANSWERS=true (intent message_content)
        if message.author.bot or message.guild is None:
            return
        session = self.games.get(message.channel.id)
        if session is None or session.answer_mode is not AnswerMode.TYPED:
            return
        self.players.setdefault(message.channel.id, {})[message.author.id] = message.author
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
                return question, await self.bot.images.get(question.subject.image_url)
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
        players = self.players.setdefault(session.channel_id, {})
        view = (
            AnswerView(session, question, players)
            if session.answer_mode is AnswerMode.BUTTONS
            else None
        )

        # La tarjeta ya dice ronda, modo, pregunta y puntos: el mensaje es solo la imagen
        # (suelta, sin embed, así se ve más grande) y los botones
        content = _round_text(session, self.bot)
        message: discord.Message | None = None
        while True:
            png = await asyncio.to_thread(_round_png, crest, session)
            file = _image_file(png, session)
            if message is None:
                kwargs = {"view": view} if view else {}
                message = await channel.send(content, file=file, **kwargs)
            else:
                await _edit_quietly(message, attachments=[file])
            try:
                # Espera a que alguien acierte (o se pare el juego) como mucho STAGE_SECONDS
                await asyncio.wait_for(session.round_over.wait(), timeout=STAGE_SECONDS)
                break
            except TimeoutError:
                if not session.next_stage():
                    break  # se acabaron las etapas y nadie acertó

        if session.round_open:
            session.close_round()
        winner = players.get(session.winner) if session.winner is not None else None
        png = await asyncio.to_thread(
            _reveal_png, crest, session, winner.display_name if winner else None
        )
        kwargs = {"view": view.reveal()} if view else {}
        await _edit_quietly(
            message,
            content=_reveal_text(session, players),
            attachments=[_image_file(png, session, "answer")],
            **kwargs,
        )
        if view:
            view.stop()

    async def _finish_game(self, session: GameSession, channel: discord.abc.Messageable) -> None:
        if session.played:
            # Se anota aunque nadie haya acertado o se haya parado: ya se vio ese escudo
            try:
                await repos.mark_seen(self.bot.db, session.guild_id, session.played)
            except Exception as e:
                log.exception("Could not save the played trivia answers")
                await self.bot.report_error("Saving played trivia answers", e)
        if session.answers:
            try:
                await repos.save_game(self.bot.db, session.result())
            except Exception as e:
                log.exception("Could not save trivia game")
                await self.bot.report_error("Saving a trivia game", e)
        known = self.players.get(session.channel_id, {})
        embed = _summary_embed(session)
        file = None
        if ranking := session.ranking():
            # Podio con avatares (issue #11); si falla, queda el resumen en texto
            try:
                players = []
                for score in ranking[:10]:
                    user = known.get(score.user_id)
                    players.append(
                        trivia_cards.PlayerEntry(
                            name=user.display_name if user else "Player",
                            avatar=await _avatar_bytes(user) if user else None,
                            points=score.points,
                        )
                    )
                png = await asyncio.to_thread(
                    trivia_cards.podium_card,
                    title="Game stopped" if session.round < session.total_rounds else "Game over",
                    subtitle=f"{session.mode.title} · {_rounds_played(session)} · "
                    f"{session.difficulty}",
                    players=players,
                )
                file = discord.File(io.BytesIO(png), filename="podium.png")
            except Exception:
                log.exception("Could not draw the podium card")
        self.players.pop(session.channel_id, None)
        # Botón para empezar otra partida igual (mismo modo, dificultad y rondas)
        again = PlayAgainView(self, session)
        if file:
            # El podio ya tiene la clasificación: el texto solo dice quién ganó
            await _send_quietly(
                channel, _summary_text(session, known, self.bot), file=file, view=again
            )
        else:
            await _send_quietly(channel, embed=embed, view=again)


class PlayAgainView(discord.ui.View):
    """El botón "Play again" del final: empieza otra partida con la misma configuración."""

    def __init__(self, cog: "Trivia", session: GameSession) -> None:
        super().__init__(timeout=600)  # 10 minutos; después el botón deja de responder
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Leaderboard", style=discord.ButtonStyle.secondary, row=0)
    async def show_leaderboard(
        self, interaction: discord.Interaction, button: discord.ui.Button["PlayAgainView"]
    ) -> None:
        # Lo mismo que escribir /leaderboard
        await self.cog.leaderboard.callback(self.cog, interaction, None)

    @discord.ui.button(label="Play again", style=discord.ButtonStyle.primary, row=0)
    async def play_again(
        self, interaction: discord.Interaction, button: discord.ui.Button["PlayAgainView"]
    ) -> None:
        s = self.session
        # Lo mismo que escribir /trivia start con las opciones de la partida anterior
        await self.cog.start.callback(
            self.cog,
            interaction,
            mode=app_commands.Choice(name=s.mode.title, value=s.mode.key),
            difficulty=app_commands.Choice(name=s.difficulty.title(), value=s.difficulty),
            rounds=s.total_rounds,
            answers=app_commands.Choice(name=s.answer_mode.value, value=s.answer_mode.value),
        )
        button.disabled = True
        self.stop()
        with contextlib.suppress(discord.HTTPException):
            if interaction.message:
                await interaction.message.edit(view=self)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        # Fuera de los slash commands, los errores no pasan por bot.py: se responden aquí
        if isinstance(error, UserFacingError):
            await interaction.response.send_message(str(error), ephemeral=True)
        else:
            await super().on_error(interaction, error, item)


class AnswerView(discord.ui.View):
    """Los 4 botones de una ronda. Cada clic llama a `session.answer` y responde solo a quien
    hizo clic (ephemeral), para no llenar el chat."""

    def __init__(
        self,
        session: GameSession,
        question: Question,
        players: dict[int, discord.abc.User],
    ) -> None:
        super().__init__(timeout=None)  # el bucle de la ronda decide cuándo se acaba
        self.session = session
        self.question = question
        self.players = players  # se anota quién responde, para nombres y avatares
        self._buttons: list[tuple[discord.ui.Button[AnswerView], TriviaItem]] = []
        for option in question.options:
            button: discord.ui.Button[AnswerView] = discord.ui.Button(
                label=f"{option.emoji} {option.name}"[:80] if option.emoji else option.name[:80],
                style=discord.ButtonStyle.secondary,
            )
            button.callback = self._callback_for(option)
            self.add_item(button)
            self._buttons.append((button, option))

    def _callback_for(
        self, option: TriviaItem
    ) -> Callable[[discord.Interaction], Coroutine[Any, Any, None]]:
        async def callback(interaction: discord.Interaction) -> None:
            self.players[interaction.user.id] = interaction.user
            outcome, points = self.session.answer(interaction.user.id, choice_id=option.id)
            score = self.session.scores.get(interaction.user.id)
            await interaction.response.send_message(
                _outcome_text(outcome, points, score, self.session), ephemeral=True
            )

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


def _round_mode(session: GameSession) -> Mode:
    """El modo de la ronda actual: el de la partida, o el que le tocó en `mix`."""
    question = session.question
    if question is not None and question.mode_key:
        return MODES[question.mode_key]
    return session.mode


def _round_seed(session: GameSession) -> int:
    """Número fijo para toda la ronda (el punto donde hace zoom no cambia entre etapas)."""
    subject = session.question.subject.id if session.question else ""
    return zlib.crc32(f"{subject}:{session.round}".encode())


# Qué pasa con la imagen en la siguiente etapa, según el efecto (para la cabecera de la ronda)
_STAGE_CUES = {"zoom": "WIDER", "silhouette": "COLOR"}


def _round_png(crest: bytes, session: GameSession) -> bytes:
    """La ronda como tarjeta. Si la tarjeta falla, solo la imagen con el efecto (como antes)."""
    mode = _round_mode(session)
    stage_image = render_stage(
        crest, mode.effect, mode.levels[session.stage], seed=_round_seed(session)
    )
    try:
        return trivia_cards.round_card(
            stage_image=stage_image,
            round_no=session.round,
            total_rounds=session.total_rounds,
            title=mode.title,
            stage=session.stage,
            points=STAGE_POINTS,
            prompt=mode.prompt,
            seconds=STAGE_SECONDS,
            cue=_STAGE_CUES.get(mode.effect),
        )
    except Exception:
        log.exception("Could not draw the round card")
        return stage_image


def _reveal_png(crest: bytes, session: GameSession, winner_name: str | None) -> bytes:
    """La respuesta como tarjeta. Si falla, solo el escudo limpio (como antes)."""
    assert session.question is not None
    answer = session.question.answer
    shown = session.question.shown
    mode = _round_mode(session)
    # club-country: el nombre grande es el país; debajo, el club que salió en la imagen
    subtitle = shown.name if shown else answer.subtitle
    points = None
    if session.winner is not None:
        points = session.answers[-1].points
        headline, success = f"{winner_name or 'Someone'} got it", True
    else:
        headline = "Game stopped" if session.stopped else "Nobody got it"
        success = False
    try:
        return trivia_cards.reveal_card(
            crest=crest,
            name=answer.name,
            subtitle=subtitle,
            headline=headline,
            success=success,
            label=f"Round {session.round}/{session.total_rounds}",
            points=points,
        )
    except Exception:
        log.exception("Could not draw the reveal card")
        return render_stage(crest, mode.effect, None)


async def _avatar_bytes(user: discord.abc.User) -> bytes | None:
    """El avatar de Discord en 128 px, o None si no se pudo bajar."""
    try:
        return await user.display_avatar.with_size(128).read()
    except discord.DiscordException:
        return None


def _image_file(png: bytes, session: GameSession, suffix: str | None = None) -> discord.File:
    # Un nombre distinto por etapa: si se repite, Discord a veces muestra la imagen anterior
    name = f"trivia-{session.round}-{suffix or session.stage}.png"
    return discord.File(io.BytesIO(png), filename=name)


def _rank_label(index: int) -> str:
    """Puesto en el texto: "`1.`", "`2.`"... (las medallas están en las tarjetas)."""
    return f"`{index + 1}.`"


def _outcome_text(
    outcome: Outcome,
    points: int,
    score: PlayerScore | None = None,
    session: GameSession | None = None,
) -> str:
    """Lo que ve solo quien hizo clic (ephemeral)."""
    match outcome:
        case Outcome.CORRECT:
            details = []
            if session:
                details.append(f"Round {session.round} of {session.total_rounds}")
            # El total solo si suma algo más que esta ronda (si no, repite el +75)
            if score and score.points != points:
                details.append(f"{score.points} points this game")
            if score and score.streak > 1:
                details.append(f"{score.streak} in a row")
            text = f"✅ **Correct!** +{points} points"
            if session and session.question:
                text = f"✅ **Correct, it's {session.question.answer.name}!** +{points} points"
            return text + ("\n-# " + " · ".join(details) if details else "")
        case Outcome.WRONG:
            return (
                "❌ **Wrong.** Your answer is locked for this round.\n"
                "-# The right one shows when the round ends."
            )
        case Outcome.ALREADY_TRIED:
            return "You already answered this round."
        case Outcome.CLOSED:
            return "Too late, this round is over."


def _start_embed(
    session: GameSession, user: discord.abc.User, client: discord.Client
) -> discord.Embed:
    """El anuncio de la partida: modo, cuándo empieza y las reglas en tres renglones cortos."""
    how = (
        "Answer with the buttons"
        if session.answer_mode is AnswerMode.BUTTONS
        else ("Type your answers in the chat")
    )
    points = " / ".join(str(p) for p in STAGE_POINTS)
    starts = timestamp(datetime.now(UTC) + timedelta(seconds=START_DELAY), "R")
    embed = discord.Embed(
        title=f"{session.mode.title} · {session.total_rounds} rounds",
        description=(
            f"{user.mention} started a game ({session.difficulty}). First round {starts}.\n"
            f"- The image gets clearer every {STAGE_SECONDS} s\n"
            f"- Answer early for more points: **{points}**\n"
            f"- Win rounds in a row for **+{STREAK_BONUS}** more each time\n"
            f"- {how} · {command_mention(client, 'trivia hint')} for a clue · "
            f"{command_mention(client, 'trivia stop')} to end"
        ),
        color=COLOR,
    )
    embed.set_thumbnail(url=LOGO_URL)  # el logo del bot (va adjunto: logo_file())
    return embed


def _round_text(session: GameSession, client: discord.Client) -> str:
    """Debajo del nombre del bot, encima de la ronda: cada cuánto se aclara y cómo pedir pista.

    Con respuestas escritas, además, qué hay que escribir.
    """
    hint = f"{command_mention(client, 'trivia hint')} for a clue"
    line = f"Round {session.round} of {session.total_rounds} · {hint}"
    if session.answer_mode is AnswerMode.BUTTONS:
        return line
    what = "country" if _round_mode(session).kind == "club-country" else "name"
    if session.mode.pool == "countries":
        what = "country"
    return f"Type the {what} in the chat.\n{line}"


def _names(players: dict[int, discord.abc.User]) -> Callable[[int], str]:
    """Nombre visible de un jugador (sin @: no notifica a nadie)."""
    return lambda user_id: players[user_id].display_name if user_id in players else "Player"


def _reveal_text(session: GameSession, players: dict[int, discord.abc.User]) -> str:
    """Debajo de la respuesta: cómo va la partida y cuándo sigue (quién acertó ya sale en la
    tarjeta)."""
    name = _names(players)
    top = session.ranking()[:3]
    lines = []
    if top:
        label = "Top 3" if len(top) == 3 else "Leaders"
        lines.append(
            f"**{label}** · " + " · ".join(f"{name(p.user_id)} **{p.points}**" for p in top)
        )
    left = session.total_rounds - session.round
    if left and not session.stopped:
        # Timestamp relativo: Discord lo muestra como "in 4 seconds" y lo va actualizando
        nxt = timestamp(datetime.now(UTC) + timedelta(seconds=BETWEEN_ROUNDS), "R")
        lines.append(f"Round {session.round} of {session.total_rounds} · next one {nxt}")
    else:
        lines.append("-# That was the last round")
    return "\n".join(lines)


def _rounds_played(session: GameSession) -> str:
    """ "10 rounds", o "3 of 10 rounds" si la partida se paró antes."""
    if session.round < session.total_rounds:
        return f"{session.round} of {session.total_rounds} rounds"
    return f"{session.total_rounds} rounds"


def _summary_text(
    session: GameSession, players: dict[int, discord.abc.User], client: discord.Client
) -> str:
    """Junto al podio: quién ganó (y si la partida se paró antes de tiempo)."""
    winner = session.ranking()[0]
    name = _names(players)(winner.user_id)
    text = f"**{name}** wins with **{winner.points}** points!"
    if session.round < session.total_rounds:
        # Partida cortada: nadie "gana", solo iba primero
        text = f"Game stopped after {_rounds_played(session)}. {name} led with {winner.points}."
    return text


def _your_rank(
    rows: list[Any], players: list[trivia_cards.PlayerEntry], user_id: int
) -> str | None:
    """Junto al ranking: dónde está quien lo pidió ("You're #3, 260 points behind Pibe")."""
    for i, row in enumerate(rows):
        if row.user_id != user_id:
            continue
        if i == 0:
            return f"You're **#1** with **{row.points:,}** points."
        gap = rows[i - 1].points - row.points
        return f"You're **#{i + 1}**, {gap:,} points behind {players[i - 1].name}."
    return None


def _summary_embed(session: GameSession) -> discord.Embed:
    """El final en texto, si no se pudo dibujar el podio (o nadie sumó puntos)."""
    embed = discord.Embed(title="Game over", color=COLOR)
    ranking = session.ranking()
    if ranking:
        winner = ranking[0]
        lines = [f"<@{winner.user_id}> wins with **{winner.points}** points."]
        lines += [
            f"{_rank_label(i)} <@{p.user_id}> **{p.points}** · {p.correct} correct"
            + (f" · streak {p.best_streak}" if p.best_streak > 1 else "")
            for i, p in enumerate(ranking[:10])
        ]
        embed.description = "\n".join(lines)
    else:
        embed.description = "Nobody scored this time. Try an easier difficulty?"
    rounds = "round" if session.round == 1 else "rounds"
    embed.set_footer(text=f"{session.round} {rounds} · /leaderboard for the server ranking")
    return embed


async def setup(bot: FootballBot) -> None:
    """discord.py la llama al cargar este archivo (bot.load_extension). Registra el cog."""
    await bot.add_cog(Trivia(bot))
