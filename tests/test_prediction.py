"""Tests for tokenisation, the language model and the typing context.

Runnable either with pytest or directly:  python tests/test_prediction.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osk.prediction.engine import PredictionEngine, RecencyCache
from osk.prediction.model import LanguageModel, fold
from osk.prediction.tokens import (
    SENTENCE_START, at_sentence_start, context_words, current_sentence,
    match_case, tokenize, trailing_prefix,
)
from osk.prediction.userstore import UserModel


def make_model() -> LanguageModel:
    """A small hand-built model, so the tests do not depend on the trained one."""
    m = LanguageModel.empty()
    m.unigram = {
        "mirë": 100, "mirëmëngjes": 40, "mira": 12, "mirupafshim": 30,
        "shqipëri": 60, "shqiptar": 25, "si": 90, "je": 70, "jam": 65,
        "faleminderit": 45, "shumë": 80, "për": 200, "të": 300, "ditë": 50,
        # A missing-diacritic misspelling (20x rarer than "për") next to a
        # genuine minimal pair that happens to differ only by a diacritic.
        "per": 10, "me": 50, "më": 55, "sot": 20, "ti": 30, "dhe": 400,
    }
    m.surface = {"shqipëri": "Shqipëri"}
    m.total = sum(m.unigram.values())
    # Each context carries the true number of times it was seen, which is not
    # the same as the sum of the continuations kept: "si" below was seen 90
    # times but only 60 of those are itemised.
    m.bigram = {
        "si": (90, [("je", 50), ("jam", 10)]),
        "shumë": (45, [("mirë", 40), ("ditë", 5)]),
        "faleminderit": (50, [("shumë", 30), ("për", 20)]),
        "je": (8, [("ti", 8)]),
        "mirë": (500, [("dhe", 400)]),
        SENTENCE_START: (135, [("si", 90), ("faleminderit", 45)]),
    }
    m.trigram = {
        "si je": (12, [("sot", 12)]),
        "faleminderit shumë": (25, [("për", 25)]),
        # Seen twice, with one continuation. Under the old winner-takes-all
        # backoff this scored a flat certainty of 1.0 and buried every bigram.
        "shumë mirë": (2, [("ditë", 2)]),
    }
    m.starters = [("si", 90), ("faleminderit", 45)]
    m._build_index()
    return m


def temp_user() -> UserModel:
    return UserModel(Path(tempfile.mkdtemp()) / "user.json")


# -- tokenisation ---------------------------------------------------------

def test_tokenize_keeps_albanian_letters():
    assert tokenize("Përshëndetje, si je?") == ["Përshëndetje", "si", "je"]


def test_tokenize_keeps_internal_apostrophe():
    assert tokenize("s'ka gjë") == ["s'ka", "gjë"]


def test_trailing_prefix():
    assert trailing_prefix("si je mir") == "mir"
    assert trailing_prefix("si je ") == ""
    assert trailing_prefix("") == ""


def test_match_case():
    assert match_case("sh", "shqipëri") == "shqipëri"
    assert match_case("Sh", "shqipëri") == "Shqipëri"
    assert match_case("SH", "shqipëri") == "SHQIPËRI"


def test_at_sentence_start():
    assert at_sentence_start("")
    assert at_sentence_start("Kjo është një fjali. ")
    assert not at_sentence_start("Kjo është ")


def test_fold_strips_albanian_diacritics():
    assert fold("Shqipëri") == "shqiperi"
    assert fold("çelës") == "celes"


# -- the language model ---------------------------------------------------

def test_completion_finds_prefix():
    m = make_model()
    words = [s.word for s in m.complete("mir", k=5)]
    assert "mirë" in words
    assert words[0] == "mirë"  # most frequent wins


def test_completion_is_diacritic_insensitive():
    """Typing without accents must still reach the accented word."""
    m = make_model()
    words = [s.word for s in m.complete("shqiperi", k=5)]
    assert "shqipëri" in words


def test_completion_prefers_the_spelling_actually_typed():
    m = make_model()
    typed_accented = [s.word for s in m.complete("mirë", k=5)]
    assert typed_accented[0] == "mirë"


def test_completion_tolerates_a_typo():
    """A doubled keypress should still find the word."""
    m = make_model()
    words = [s.word for s in m.complete("mirrup", k=5)]
    assert "mirupafshim" in words


def test_next_word_uses_bigrams():
    m = make_model()
    words = [s.word for s in m.next_words(prev1="si", k=3)]
    assert words[0] == "je"


def test_next_word_prefers_trigram_over_bigram():
    m = make_model()
    words = [s.word for s in m.next_words(prev1="shumë", prev2="faleminderit", k=3)]
    assert words[0] == "për"          # from the trigram
    assert "mirë" in words            # bigram evidence still present


def test_context_reranks_completions():
    """After "shumë", the completion "mirë" should outrank the commoner "mira"."""
    m = make_model()
    words = [s.word for s in m.complete("mir", prev1="shumë", k=5)]
    assert words[0] == "mirë"


def test_resolve_context_maps_unaccented_input():
    m = make_model()
    m.bigram["për"] = [("ty", 5)]
    m._build_index()
    assert m.resolve_context("per") == "për"


def test_canonicalize_repairs_a_missing_diacritic():
    """"per" is a misspelling of "për" and must never be offered as a word."""
    m = make_model()
    assert m.canonicalize("per") == "për"


def test_canonicalize_leaves_genuine_minimal_pairs_alone():
    """me and më are different Albanian words; neither may absorb the other."""
    m = make_model()
    assert m.canonicalize("me") == "me"
    assert m.canonicalize("më") == "më"


def test_canonicalize_never_strips_diacritics():
    m = make_model()
    for word in m.unigram:
        assert m.canonicalize(word) == word or fold(word) == word


def test_suggestions_are_correctly_accented():
    e = make_engine()
    e.on_text("faleminderit ")
    assert "per" not in [w.lower() for w in e.suggestions(6)]


def test_empty_model_answers_nothing():
    m = LanguageModel.empty()
    assert m.complete("mir") == []
    assert m.next_words(prev1="si") == []


def test_probability_uses_the_true_context_total_not_the_kept_sum():
    """A truncated continuation list must not inflate what survived it.

    "si" was seen 90 times; only 60 of those are itemised. Reading the total off
    the stored list would put P(je|si) at 50/60 instead of 50/90.
    """
    m = make_model()
    ctx = m.context(prev1="si")
    assert abs(ctx.p_bi["je"] - 50 / 90) < 1e-9


def test_a_thin_trigram_does_not_override_a_strong_bigram():
    """The bug this model was rebuilt to fix.

    "shumë mirë" was seen twice and always followed by "ditë"; "mirë" was seen
    500 times and followed by "dhe" in 400 of them. Taking the highest-order
    match outright made the twice-seen trigram a certainty and buried "dhe".
    """
    m = make_model()
    words = [s.word for s in m.next_words(prev1="mirë", prev2="shumë", k=5)]
    assert words[0] == "dhe"
    assert "ditë" in words          # the trigram still counts for something


def test_a_well_attested_trigram_still_wins():
    """Discounting weak evidence must not amount to ignoring strong evidence."""
    m = make_model()
    words = [s.word for s in m.next_words(prev1="shumë", prev2="faleminderit", k=3)]
    assert words[0] == "për"


def test_suggestions_fill_out_when_the_context_is_thin():
    """Empty buttons help nobody, so common words back-fill the rows."""
    m = make_model()
    assert len(m.next_words(prev1="je", k=12)) == 12


def test_recency_cache_lifts_a_word_that_was_just_used():
    cache = RecencyCache()
    for _ in range(6):
        cache.observe("mjekësor")
    m = make_model()
    plain = [s.word for s in m.next_words(prev1="si", k=6)]
    cached = [s.word for s in m.next_words(prev1="si", k=6, cache=cache.probs(),
                                           cache_weight=0.3)]
    assert "mjekësor" not in plain
    assert "mjekësor" in cached


def test_recency_cache_decays():
    cache = RecencyCache()
    cache.observe("harrohet")
    for i in range(3000):
        cache.observe(f"fjala{i}")
    assert "harrohet" not in cache.probs()


# -- the engine -----------------------------------------------------------

def make_engine() -> PredictionEngine:
    e = PredictionEngine(None, temp_user())
    e.model = make_model()
    return e


def test_engine_tracks_prefix_and_context():
    e = make_engine()
    e.on_text("si je mir")
    assert e.prefix == "mir"
    assert e._previous_words() == ("je", "si")


def test_engine_suggests_completions_then_next_words():
    e = make_engine()
    e.on_text("shumë ")
    assert "Mirë" in e.suggestions(5) or "mirë" in e.suggestions(5)
    e.on_text("mir")
    assert "mirë" in e.suggestions(5)


def test_engine_capitalises_at_sentence_start():
    e = make_engine()
    e.on_text("Kjo mbaroi. ")
    assert all(w[0].isupper() for w in e.suggestions(3))


def test_engine_shows_proper_nouns_capitalised():
    e = make_engine()
    e.on_text("shqiperi")
    assert "Shqipëri" in e.suggestions(5)


def test_accept_extends_a_matching_prefix():
    e = make_engine()
    e.on_text("mir")
    plan = e.plan_accept("mirë")
    assert plan.backspaces == 0
    assert plan.text == "ë "


def test_accept_replaces_a_non_matching_prefix():
    """Accepting an accented word typed without accents rewrites the whole word."""
    e = make_engine()
    e.on_text("shqiperi")
    plan = e.plan_accept("Shqipëri")
    assert plan.backspaces == len("shqiperi")
    assert plan.text == "Shqipëri "


def test_accept_without_auto_space():
    e = make_engine()
    e.auto_space = False
    e.on_text("mir")
    assert e.plan_accept("mirë").text == "ë"


def test_backspace_shortens_context():
    e = make_engine()
    e.on_text("mirë")
    e.on_backspace()
    assert e.prefix == "mir"


def test_backspace_past_the_start_drops_context():
    """We cannot see text we did not type, so the context is abandoned."""
    e = make_engine()
    e.on_text("ab")
    e.on_backspace(5)
    assert e.buffer == ""


def test_navigation_resets_context():
    e = make_engine()
    e.on_text("si je")
    e.on_navigation()
    assert e.buffer == ""


def test_context_stops_at_the_end_of_a_sentence():
    """After a full stop the question is what opens a sentence, not what
    follows the last word of the one before it."""
    e = make_engine()
    e.on_text("shkova në shtëpi. ")
    assert e._previous_words()[0] == SENTENCE_START


def test_context_carries_within_a_sentence():
    e = make_engine()
    e.on_text("shkova. si je ")
    assert e._previous_words() == ("je", "si")


def test_first_word_of_a_sentence_sees_the_start_marker():
    e = make_engine()
    e.on_text("mbaroi. si ")
    assert e._previous_words() == ("si", SENTENCE_START)


def test_current_sentence_splits_on_the_last_full_stop():
    assert current_sentence("Njëra. Tjetra dhe ") == "Tjetra dhe "
    assert current_sentence("pa pikë fare") == "pa pikë fare"


def test_context_words_open_with_the_start_marker():
    assert context_words("si je") == [SENTENCE_START, "si", "je"]


def test_recency_survives_a_context_reset():
    """Switching window invalidates the caret, not the subject being written."""
    e = make_engine()
    e.on_text("mjekësor ")
    e.reset()
    assert "mjekësor" in e.recent.probs()


def test_recency_records_even_when_learning_is_off():
    """The cache is working memory, not a record: turning off learning stops
    words being kept between sessions, not the current subject being tracked."""
    e = make_engine()
    e.learn = False
    e.on_text("mjekësor ")
    assert e.user.unigram == {}
    assert "mjekësor" in e.recent.probs()


def test_buffer_stays_bounded():
    e = make_engine()
    e.on_text("fjalë " * 400)
    assert len(e.buffer) <= 700


# -- learning -------------------------------------------------------------

def test_user_model_learns_and_ranks_new_words():
    e = make_engine()
    for _ in range(5):
        e.on_text("Prishtinë ")
    assert "prishtinë" in e.user.unigram
    e.reset()
    e.on_text("prish")
    assert "prishtinë" in [w.lower() for w in e.suggestions(5)]


def test_user_model_learns_bigrams():
    e = make_engine()
    for _ in range(4):
        e.on_text("takimi mjekësor ")
        e.reset()
    e.on_text("takimi ")
    assert "mjekësor" in [w.lower() for w in e.suggestions(6)]


def test_user_model_round_trips_to_disk():
    path = Path(tempfile.mkdtemp()) / "user.json"
    u = UserModel(path)
    u.observe("prishtinë", "në")
    u.save()
    again = UserModel(path)
    assert again.unigram.get("prishtinë") == 1.0
    assert again.bigram["në"]["prishtinë"] == 1.0


def test_user_model_clear():
    u = temp_user()
    u.observe("fjalë")
    u.clear()
    assert u.unigram == {}


def test_learning_can_be_switched_off():
    e = make_engine()
    e.learn = False
    e.on_text("fjalëpapare ")
    assert e.user.unigram == {}


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
