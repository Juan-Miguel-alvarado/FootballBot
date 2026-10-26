"""Utilidades de texto para buscar sin importar tildes, mayúsculas ni signos.

Quién lo usa: la búsqueda de ligas (services/leagues.py) y de equipos (services/football.py).
En la Fase 2 también lo usará la trivia para comparar respuestas escritas.
"""

import re

from unidecode import unidecode

# Cualquier cosa que no sea letra minúscula o número (espacios, tildes ya quitadas, signos...).
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation: 'Atlético  Madrid!' -> 'atletico madrid'."""
    # unidecode: "Atlético" -> "Atletico", "Barça" -> "Barca".
    # Puntos y apóstrofos se quitan sin dejar espacio: "C.F." -> "cf", "M'gladbach" -> "mgladbach".
    # Todo lo demás que no sea letra o número -> un espacio.
    text = unidecode(text).lower().replace(".", "").replace("'", "")
    return _NON_ALNUM.sub(" ", text).strip()
