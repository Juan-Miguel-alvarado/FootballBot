-- Tablas de la trivia (Fase 2). Ver storage/db.py para cómo se aplican las migraciones.
-- Las fechas se guardan como texto ISO 8601 en UTC: '2026-10-26T15:04:05+00:00'.

-- Una fila por partida terminada
CREATE TABLE games (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    mode        TEXT    NOT NULL,   -- crest, blur, league
    difficulty  TEXT    NOT NULL,   -- easy, medium, hard
    rounds      INTEGER NOT NULL,   -- rondas jugadas
    started_at  TEXT    NOT NULL,
    ended_at    TEXT    NOT NULL
);

-- Cada respuesta registrada (aciertos y fallos con botones)
CREATE TABLE answers (
    game_id     INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    round       INTEGER NOT NULL,
    correct     INTEGER NOT NULL,   -- 1 o 0 (SQLite no tiene booleanos)
    stage       INTEGER NOT NULL,   -- 0 = imagen más difícil
    points      INTEGER NOT NULL,
    answered_at TEXT    NOT NULL
);

-- Totales por servidor, jugador y modo. Se actualiza al terminar cada partida;
-- /leaderboard lee de aquí para no sumar todas las respuestas cada vez.
CREATE TABLE scores (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    mode        TEXT    NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    answered    INTEGER NOT NULL DEFAULT 0,
    played      INTEGER NOT NULL DEFAULT 0,   -- partidas en las que respondió algo
    best_streak INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, mode)
);

CREATE INDEX answers_game ON answers (game_id);
