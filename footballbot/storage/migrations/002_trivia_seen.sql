-- Qué respuestas de la trivia ya salieron en cada servidor y cuándo (issue #9).
-- QuestionPicker (services/trivia/modes.py) lo usa para no repetir escudos entre partidas:
-- primero salen los que nunca salieron y después los que hace más tiempo que no salen.
-- item_id es el id de TriviaItem ("team-86", "league-PL"), así los modos que usan el mismo
-- escudo (crest, blur...) comparten la memoria.
CREATE TABLE trivia_seen (
    guild_id     INTEGER NOT NULL,
    item_id      TEXT    NOT NULL,
    last_seen_at TEXT    NOT NULL,   -- ISO 8601 en UTC
    PRIMARY KEY (guild_id, item_id)
);
