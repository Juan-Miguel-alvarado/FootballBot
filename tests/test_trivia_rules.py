"""Tests de la lógica de la trivia sin Discord: respuestas escritas (matching.py), dataset real
(dataset.py), modos y preguntas (modes.py) y reglas de puntos (session.py).
"""

import random

import pytest

from footballbot.models import Question, TriviaItem
from footballbot.services.trivia.dataset import load_dataset
from footballbot.services.trivia.matching import is_correct, simplify
from footballbot.services.trivia.modes import MODES, QuestionPicker, pool_for
from footballbot.services.trivia.session import (
    STAGE_POINTS,
    AnswerMode,
    GameSession,
    Outcome,
)


def item(n: int, name: str | None = None, country: str = "Spain") -> TriviaItem:
    """Un club de prueba."""
    name = name or f"Club {n}"
    return TriviaItem(
        id=f"team-{n}",
        name=name,
        full_name=name,
        answers=(simplify(name),),
        image_url=f"https://example.com/{n}.png",
        difficulty=1,
        country=country,
    )


# --- matching ----------------------------------------------------------------------------------


def test_simplify_drops_noise_words() -> None:
    assert simplify("Real Madrid C.F.") == "real madrid"
    assert simplify("Club Atlético de Madrid") == "atletico madrid"
    # Si solo hay palabras "de relleno", se conservan
    assert simplify("AC") == "ac"


@pytest.mark.parametrize(
    "guess",
    ["Atletico Madrid", "atlético", "ATLETI", "atletico de madird", "  Atlético de Madrid!! "],
)
def test_is_correct_accepts_variants(guess: str) -> None:
    answers = tuple(simplify(n) for n in ["Club Atlético de Madrid", "Atleti", "atletico"])
    assert is_correct(guess, answers)


@pytest.mark.parametrize("guess", ["madrid", "real madrid", "", "atl", "psg"])
def test_is_correct_rejects(guess: str) -> None:
    answers = tuple(simplify(n) for n in ["Club Atlético de Madrid", "Atleti", "atletico", "psv"])
    assert not is_correct(guess, answers)


# --- dataset real (data/dataset/) --------------------------------------------------------------


def test_real_dataset_loads() -> None:
    dataset = load_dataset()
    assert len(dataset.teams) > 150
    assert len(dataset.leagues) == 13
    assert all(t.image_url.endswith(".png") for t in dataset.teams)
    assert {t.difficulty for t in dataset.teams} == {1, 2, 3}


def test_real_dataset_uses_aliases() -> None:
    teams = {t.id: t for t in load_dataset().teams}
    real = teams["team-86"]
    assert real.name == "Real Madrid"  # nombre de aliases.json
    assert real.full_name == "Real Madrid CF"  # nombre de la API
    assert is_correct("los blancos", real.answers)
    assert is_correct("barca", teams["team-81"].answers)


def test_league_answers_include_codes_and_aliases() -> None:
    leagues = {lg.id: lg for lg in load_dataset().leagues}
    premier = leagues["league-PL"]
    assert is_correct("Premier League", premier.answers)
    assert is_correct("epl", premier.answers)


# --- modos y preguntas -------------------------------------------------------------------------


def test_harder_difficulties_include_more_teams() -> None:
    dataset = load_dataset()
    mode = MODES["crest"]
    sizes = [len(pool_for(mode, dataset, d)) for d in ("easy", "medium", "hard")]
    assert sizes[0] < sizes[1] < sizes[2] == len(dataset.teams)
    assert len(pool_for(MODES["league"], dataset, "hard")) == 13


def test_picker_gives_four_distinct_options_with_the_answer() -> None:
    pool = [item(i) for i in range(10)]
    picker = QuestionPicker(pool, random.Random(1))
    for _ in range(10):
        question = picker.next()
        names = [o.name for o in question.options]
        assert len(names) == 4 == len(set(names))
        assert question.answer in question.options


def test_picker_never_repeats_an_answer() -> None:
    picker = QuestionPicker([item(i) for i in range(6)], random.Random(2))
    answers = [picker.next().answer.id for _ in range(6)]
    assert len(set(answers)) == 6
    with pytest.raises(IndexError):
        picker.next()


def test_picker_avoids_duplicate_names_in_options() -> None:
    pool = [item(1, "Liverpool", "England"), item(2, "Liverpool", "Uruguay")]
    pool += [item(i) for i in range(3, 8)]
    picker = QuestionPicker(pool, random.Random(3))
    for _ in range(len(pool)):
        names = [o.name for o in picker.next().options]
        assert names.count("Liverpool") <= 1


def test_picker_prefers_same_country() -> None:
    answer_pool = [item(1, "A", "Italy"), item(2, "B", "Italy"), item(3, "C", "Italy")]
    others = [item(i, f"X{i}", "Brazil") for i in range(4, 20)]
    picker = QuestionPicker(answer_pool + others, random.Random(4))
    question = next(q for q in (picker.next() for _ in range(19)) if q.answer.name == "A")
    italian = [o for o in question.options if o.country == "Italy"]
    assert len(italian) == 3  # la respuesta + 2 opciones del mismo país


# --- sesión: reglas de puntos ------------------------------------------------------------------


def new_session(answer_mode: AnswerMode = AnswerMode.BUTTONS, rounds: int = 3) -> GameSession:
    return GameSession(
        guild_id=1,
        channel_id=2,
        started_by=10,
        mode=MODES["crest"],
        difficulty="easy",
        rounds=rounds,
        answer_mode=answer_mode,
    )


def question(n: int = 1) -> Question:
    answer = item(n, f"Answer {n}")
    return Question(answer=answer, options=(answer, item(90), item(91), item(92)))


def test_correct_button_answer_scores_by_stage() -> None:
    session = new_session()
    session.start_round(question())
    session.next_stage()  # etapa 2 de 4
    outcome, points = session.answer(100, choice_id="team-1")
    assert (outcome, points) == (Outcome.CORRECT, STAGE_POINTS[1])
    assert session.winner == 100
    assert not session.round_open
    assert session.round_over.is_set()
    # Después de cerrarse la ronda nadie más puntúa
    assert session.answer(200, choice_id="team-1") == (Outcome.CLOSED, 0)


def test_wrong_button_locks_the_player_out_for_the_round() -> None:
    session = new_session()
    session.start_round(question())
    assert session.answer(100, choice_id="team-90") == (Outcome.WRONG, 0)
    assert session.answer(100, choice_id="team-1") == (Outcome.ALREADY_TRIED, 0)
    assert session.answer(200, choice_id="team-1")[0] is Outcome.CORRECT
    assert [(a.user_id, a.correct) for a in session.answers] == [(100, False), (200, True)]


def test_wrong_typed_answers_are_free() -> None:
    session = new_session(AnswerMode.TYPED)
    session.start_round(question())
    assert session.answer(100, text="no idea") == (Outcome.WRONG, 0)
    assert session.answer(100, text="answer 1")[0] is Outcome.CORRECT
    assert len(session.answers) == 1  # el fallo escrito no se guarda


def test_streak_bonus_and_reset() -> None:
    session = new_session(rounds=4)
    for n in (1, 2, 3):
        session.start_round(question(n))
        session.answer(100, choice_id=f"team-{n}")
    score = session.scores[100]
    assert score.points == 100 + 110 + 120
    assert score.streak == score.best_streak == 3

    session.start_round(question(4))
    session.answer(200, choice_id="team-4")
    assert session.scores[100].streak == 0
    assert session.scores[100].best_streak == 3
    assert session.finished


def test_stop_ends_the_game() -> None:
    session = new_session(rounds=10)
    session.start_round(question())
    session.stop()
    assert session.finished
    assert session.round_over.is_set()
    assert session.answer(100, choice_id="team-1") == (Outcome.CLOSED, 0)


def test_result_for_the_database() -> None:
    session = new_session(rounds=2)
    session.start_round(question(1))
    session.answer(100, choice_id="team-90")
    session.answer(200, choice_id="team-1")
    result = session.result()
    assert result.rounds == 1
    assert result.mode == "crest"
    assert [p.user_id for p in result.players] == [200, 100]
    assert len(result.answers) == 2
