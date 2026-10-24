"""Modelos compartidos. Permite escribir `from footballbot.models import Team`.

Las clases están en `models/football.py`. Si añades un modelo nuevo, impórtalo aquí también
y añádelo a `__all__`.
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

__all__ = ["Competition", "Match", "MatchStatus", "Player", "Standing", "StandingRow", "Team"]
