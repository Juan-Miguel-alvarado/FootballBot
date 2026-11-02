"""Tests de la lógica de la trivia sin Discord: respuestas escritas (matching.py), dataset real
(dataset.py), modos y preguntas (modes.py) y reglas de puntos (session.py).
"""

import random
from collections import Counter
from datetime import UTC, datetime, timedelta

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


# --- sin repetir entre partidas (issue #9) -----------------------------------------------------


def play_games(pool: list[TriviaItem], games: int, rounds: int, seed: int) -> list[list[str]]:
    """Simula partidas seguidas en un servidor, recordando lo que salió como hace el bot."""
    rng = random.Random(seed)
    seen: dict[str, datetime] = {}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    played = []
    for game in range(games):
        picker = QuestionPicker(pool, rng, last_seen=seen)
        answers = [picker.next().answer.id for _ in range(rounds)]
        played.append(answers)
        for item_id in answers:  # lo que hace repos.mark_seen al terminar
            seen[item_id] = now + timedelta(minutes=game)
    return played


def test_no_repeats_across_games_until_the_pool_runs_out() -> None:
    pool = [item(i) for i in range(96)]
    games = play_games(pool, games=9, rounds=10, seed=5)  # 90 rondas de 96 posibles
    flat = [a for game in games for a in game]
    assert len(flat) == len(set(flat))


def test_after_the_pool_runs_out_the_oldest_come_first() -> None:
    pool = [item(i) for i in range(20)]
    games = play_games(pool, games=3, rounds=10, seed=6)
    # Partidas 1 y 2 agotan las 20; la 3 repite las de la partida 1 (las más viejas)
    assert set(games[2]) == set(games[0])
    assert not set(games[2]) & set(games[1])


def test_old_behaviour_without_memory_still_works() -> None:
    picker = QuestionPicker([item(i) for i in range(8)], random.Random(7))
    assert len({picker.next().answer.id for _ in range(8)}) == 8


def test_wrong_options_vary_within_a_game() -> None:
    pool = [item(i) for i in range(40)]
    picker = QuestionPicker(pool, random.Random(8))
    uses: Counter[str] = Counter()
    for _ in range(10):
        q = picker.next()
        uses.update(o.id for o in q.options if o.id != q.answer.id)
    # 30 opciones falsas repartidas entre 39 clubes: ninguno debería salir más de 2 veces
    assert max(uses.values()) <= 2


# --- modos nuevos y pistas (issue #12) ---------------------------------------------------------


def test_every_mode_has_one_level_per_stage() -> None:
    from footballbot.imaging.effects import EFFECTS

    for mode in MODES.values():
        assert len(mode.levels) == len(STAGE_POINTS), mode.key
        assert mode.effect in EFFECTS, mode.key


@pytest.mark.parametrize("key", list(MODES))
def test_every_mode_makes_valid_questions(key: str) -> None:
    from footballbot.services.trivia.modes import MIX_MODES, make_picker

    dataset = load_dataset()
    picker = make_picker(MODES[key], dataset, "hard", rng=random.Random(9))
    for _ in range(min(10, picker.remaining)):
        q = picker.next()
        names = [o.name for o in q.options]
        assert len(names) == 4 == len(set(names))
        assert q.answer in q.options
        if key == "club-country":
            assert q.shown is not None and q.shown.id.startswith("team-")
            assert q.answer == dataset.country_of(q.shown)
            assert all(o.id.startswith("country-") for o in q.options)
        if key == "flag":
            assert q.answer.image_url.startswith("https://flagcdn.com/")
            assert all(o.emoji for o in q.options)
        if key == "mix":
            assert q.mode_key in MIX_MODES


def test_countries_dataset() -> None:
    from footballbot.services.trivia.dataset import flag_emoji

    dataset = load_dataset()
    assert len(dataset.countries) >= 60
    assert flag_emoji("es") == "🇪🇸"
    assert flag_emoji("gb-nir") == "🇬🇧"
    # Todos los clubes tienen su país en countries.json
    assert all(dataset.country_of(team) for team in dataset.teams)
    spain = next(c for c in dataset.countries if c.name == "Spain")
    assert is_correct("España", spain.answers)


def test_club_country_remembers_the_club_not_the_country() -> None:
    from footballbot.services.trivia.modes import make_picker

    session = new_session()
    picker = make_picker(MODES["club-country"], load_dataset(), "easy", rng=random.Random(3))
    session.start_round(picker.next())
    assert session.played[0].startswith("team-")


def test_hints_cost_points_and_run_out() -> None:
    from footballbot.services.trivia.session import HINT_COST, MAX_HINTS, MIN_POINTS

    session = new_session()
    assert session.hint(100) is None  # todavía no hay ronda
    session.start_round(question())
    hints = [session.hint(100) for _ in range(MAX_HINTS + 1)]
    assert hints[-1] == "No more hints this round."
    _, points = session.answer(100, choice_id="team-1")
    assert points == max(MIN_POINTS, STAGE_POINTS[0] - HINT_COST * MAX_HINTS)
    # Las pistas son por ronda: en la siguiente vuelve a ganar todo
    session.start_round(question(2))
    _, points = session.answer(100, choice_id="team-2")
    assert points == STAGE_POINTS[0] + 10  # +10 de racha


def test_hint_texts_go_from_vague_to_clear() -> None:
    from footballbot.services.trivia.session import hint_text

    teams = {t.id: t for t in load_dataset().teams}
    real = teams["team-86"]
    assert hint_text(real, 0) == "Country: Spain"
    assert hint_text(real, 1) == "Plays in: La Liga"
    assert hint_text(real, 2) == "10 letters: R _ _ _ · _ _ _ _ _ _"
