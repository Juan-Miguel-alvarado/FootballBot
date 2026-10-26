"""¿La respuesta escrita es correcta? Tolera tildes, mayúsculas, "FC"/"CF" y errores de tipeo.

Quién lo usa: services/trivia/dataset.py (prepara las respuestas aceptadas de cada club)
y services/trivia/session.py (compara lo que escribió el jugador).

Ejemplos que cuentan como "Club Atlético de Madrid": "atletico madrid", "Atlético", "atleti",
"atletico de madird" (error de tipeo). Los apodos vienen de data/dataset/aliases.json.
"""

from rapidfuzz import fuzz, process

from footballbot.services.text import normalize

# Palabras que no ayudan a distinguir un club: "Real Madrid CF" y "real madrid" son lo mismo.
STOPWORDS = frozenset(
    {
        "fc", "cf", "afc", "sc", "ac", "as", "cd", "ca", "cr", "ec", "se", "sl", "sv", "ssc",
        "us", "rc", "rcd", "ud", "sd", "club", "de", "del", "da", "do", "the", "1",
    }
)  # fmt: skip

# Qué tan parecido tiene que ser (0-100). 85 acepta un error en una palabra de ~7 letras.
FUZZY_THRESHOLD = 85
# Las respuestas cortas ("om", "psv") tienen que escribirse exactas: con fuzzy, "psg"≈"psv".
MIN_FUZZY_LENGTH = 5


def simplify(text: str) -> str:
    """'Real Madrid C.F.' -> 'real madrid'. Si todo eran stopwords, deja el texto normalizado."""
    normalized = normalize(text)
    words = [w for w in normalized.split() if w not in STOPWORDS]
    return " ".join(words) or normalized


def is_correct(guess: str, answers: tuple[str, ...]) -> bool:
    """`answers` ya viene simplificado (ver dataset.py). `guess` es el texto tal cual."""
    simple = simplify(guess)
    if not simple:
        return False
    if simple in answers:
        return True
    if len(simple) < MIN_FUZZY_LENGTH:
        return False
    long_answers = [a for a in answers if len(a) >= MIN_FUZZY_LENGTH]
    match = process.extractOne(
        simple, long_answers, scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD
    )
    return match is not None
