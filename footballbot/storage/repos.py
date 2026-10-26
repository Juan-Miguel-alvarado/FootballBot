"""Consultas a la base de datos. El resto del bot usa estas funciones, nunca SQL directo.

Quién lo usa: cogs/trivia.py (guardar partidas y mostrar /leaderboard).

Para añadir una consulta: escribe una función async que reciba `db: Database`, use
`db.conn.execute(...)` con parámetros `?` (nunca armes el SQL con f-strings: inyección SQL)
y devuelva modelos o dataclasses, no filas crudas.
"""

from dataclasses import dataclass

from footballbot.models import GameResult
from footballbot.storage.db import Database


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    user_id: int
    points: int
    correct: int
    answered: int
    played: int
    best_streak: int


async def save_game(db: Database, game: GameResult) -> int:
    """Guarda una partida: la partida, cada respuesta y suma los totales de cada jugador.

    Todo va en una transacción: o se guarda completo o no se guarda nada. Devuelve el id.
    """
    conn = db.conn
    try:
        cursor = await conn.execute(
            "INSERT INTO games (guild_id, channel_id, mode, difficulty, rounds, started_at,"
            " ended_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                game.guild_id,
                game.channel_id,
                game.mode,
                game.difficulty,
                game.rounds,
                game.started_at.isoformat(),
                game.ended_at.isoformat(),
            ),
        )
        game_id = cursor.lastrowid
        assert game_id is not None
        await conn.executemany(
            "INSERT INTO answers (game_id, user_id, round, correct, stage, points, answered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (game_id, a.user_id, a.round, int(a.correct), a.stage, a.points,
                 a.answered_at.isoformat())
                for a in game.answers
            ],
        )  # fmt: skip
        # "UPSERT": si el jugador no tiene fila en este servidor y modo, se crea;
        # si ya tiene, se suman los valores (y best_streak se queda con el mayor).
        await conn.executemany(
            """
            INSERT INTO scores (guild_id, user_id, mode, points, correct, answered, played,
                                best_streak)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT (guild_id, user_id, mode) DO UPDATE SET
                points = points + excluded.points,
                correct = correct + excluded.correct,
                answered = answered + excluded.answered,
                played = played + 1,
                best_streak = MAX(best_streak, excluded.best_streak)
            """,
            [
                (game.guild_id, p.user_id, game.mode, p.points, p.correct, p.answered,
                 p.best_streak)
                for p in game.players
            ],
        )  # fmt: skip
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    return game_id


async def leaderboard(
    db: Database, guild_id: int, mode: str | None = None, limit: int = 10
) -> list[LeaderboardRow]:
    """Los mejores jugadores de un servidor. Sin `mode`, suma todos los modos."""
    query = """
        SELECT user_id,
               SUM(points) AS points, SUM(correct) AS correct, SUM(answered) AS answered,
               SUM(played) AS played, MAX(best_streak) AS best_streak
        FROM scores
        WHERE guild_id = ? AND (? IS NULL OR mode = ?)
        GROUP BY user_id
        ORDER BY points DESC, correct DESC
        LIMIT ?
    """
    async with db.conn.execute(query, (guild_id, mode, mode, limit)) as cursor:
        rows = await cursor.fetchall()
    return [
        LeaderboardRow(
            user_id=row["user_id"],
            points=row["points"],
            correct=row["correct"],
            answered=row["answered"],
            played=row["played"],
            best_streak=row["best_streak"],
        )
        for row in rows
    ]
