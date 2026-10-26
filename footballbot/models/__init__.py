"""Modelos compartidos. Permite escribir `from footballbot.models import Team`.

Las clases están en `models/football.py` (datos de fútbol) y `models/trivia.py` (trivia).
Si añades un modelo nuevo, impórtalo aquí también y añádelo a `__all__`.
"""

from footballbot.models.football import (
    Competition,
    Match,
    MatchStatus,
    Player,
    Standing,
    StandingRow,
    Team,
)
from footballbot.models.trivia import (
    AnswerRecord,
    GameResult,
    PlayerScore,
    Question,
    TriviaItem,
)

__all__ = [
    "AnswerRecord",
    "Competition",
    "GameResult",
    "Match",
    "MatchStatus",
    "Player",
    "PlayerScore",
    "Question",
    "Standing",
    "StandingRow",
    "Team",
    "TriviaItem",
]
