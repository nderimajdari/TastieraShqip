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
from osk.prediction.sentences import SentenceBank, learnable, normalise
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


def temp_bank(builtin: bool = False) -> SentenceBank:
    """A sentence store in a scratch directory.

    Never the default path: the default is the real one under %APPDATA%, and a
    test run must not write the user's own sentences file -- nor read it, since
    the ranking assertions would then depend on what they had been writing.
    """
    return SentenceBank(Path(tempfile.mkdtemp()) / "sentences.json",
                        builtin=builtin)


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
    e = PredictionEngine(None, temp_user(), temp_bank())
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


# -- multi-word suggestions -----------------------------------------------

def test_a_confident_continuation_is_bundled_into_one_suggestion():
    """"mirë" is followed by "dhe" 400 times in 500: one press, not two."""
    e = make_engine()
    e.on_text("shumë ")
    assert "mirë dhe" in e.suggestions(8)


def test_a_bundled_phrase_sits_next_to_the_word_it_extends():
    """The far end of the last row is the most expensive button on the board."""
    e = make_engine()
    e.on_text("shumë ")
    words = e.suggestions(8)
    assert words.index("mirë dhe") == words.index("mirë") + 1


def test_an_unsure_continuation_is_not_bundled():
    """"si" is followed by "je" only 50 times in 90 -- not enough to commit to."""
    e = make_engine()
    e.on_text("faleminderit ")
    assert not any(w.startswith("si ") for w in e.suggestions(8))


def test_phrases_can_be_switched_off():
    e = make_engine()
    e.phrases = False
    e.on_text("shumë ")
    assert all(" " not in w for w in e.suggestions(8))


def test_a_phrase_completes_a_half_typed_word():
    e = make_engine()
    e.on_text("shumë mir")
    assert "mirë dhe" in e.suggestions(8)


def test_accepting_a_phrase_types_only_what_is_missing():
    e = make_engine()
    e.on_text("shumë mir")
    plan = e.plan_accept("mirë dhe")
    assert plan.backspaces == 0
    assert plan.text == "ë dhe "


def test_a_phrase_never_crowds_out_more_than_its_share():
    e = make_engine()
    e.on_text("shumë ")
    words = e.suggestions(14)
    assert len(words) == 14
    assert sum(" " in w for w in words) <= 3


# -- punctuation and capitals ---------------------------------------------

def test_a_space_this_keyboard_added_is_taken_back_out_for_a_full_stop():
    """Otherwise auto-space writes "fjala ." and every sentence costs a
    trip to Backspace to repair."""
    e = make_engine()
    e.on_text("shumë ")
    plan = e.plan_accept("mirë")
    e.on_text(plan.text, auto_space=plan.auto_space)
    assert e.pending_auto_space()
    assert e.plan_punctuation(".")
    assert e.plan_punctuation(",")


def test_a_space_the_user_typed_is_left_alone():
    """Removing it would be the keyboard editing text it was not asked to."""
    e = make_engine()
    e.on_text("mirë")
    e.on_text(" ")
    assert not e.pending_auto_space()
    assert not e.plan_punctuation(".")


def test_an_ordinary_letter_never_eats_the_space():
    e = make_engine()
    e.on_text("shumë ")
    plan = e.plan_accept("mirë")
    e.on_text(plan.text, auto_space=plan.auto_space)
    assert not e.plan_punctuation("a")


def test_the_pending_space_does_not_survive_more_typing():
    e = make_engine()
    e.on_text("shumë ")
    plan = e.plan_accept("mirë")
    e.on_text(plan.text, auto_space=plan.auto_space)
    e.on_text("d")
    assert not e.pending_auto_space()


def test_sentence_start_is_reported_only_between_words():
    e = make_engine()
    e.on_text("Kjo mbaroi. ")
    assert e.at_sentence_start
    e.on_text("s")
    # Halfway through a word the question does not arise: capitalising here
    # would turn "Si" into "SI".
    assert not e.at_sentence_start


def test_sentence_start_is_false_mid_sentence():
    e = make_engine()
    e.on_text("shumë ")
    assert not e.at_sentence_start


# -- whole sentences ------------------------------------------------------

def test_normalise_rejects_what_is_not_worth_a_row():
    assert normalise("  Po   mirë,  faleminderit. ") == "Po mirë, faleminderit."
    assert normalise("Po.") == ""            # one word, and already one press
    assert normalise("") == ""
    assert normalise("12 34 56") == ""       # no letters at all
    assert normalise("x" * 400) == ""        # a paragraph, not a sentence


def test_sentences_with_long_digit_runs_are_never_stored():
    # A card number, a code or a telephone number must not be learned and then
    # offered back on a keyboard somebody else can see.
    bank = temp_bank()
    assert not learnable("Kodi im është 481920371.")
    assert not bank.observe("Kodi im është 481920371.")
    assert len(bank) == 0
    # An ordinary year or house number is not a secret and is still learned.
    assert bank.observe("Kam lindur në vitin 1994.")
    assert len(bank) == 1


def test_bank_offers_what_was_written_before():
    bank = temp_bank()
    bank.observe("Do të përgjigjem nesër.")
    assert bank.matches("") == ["Do të përgjigjem nesër."]


def test_bank_matches_on_the_opening_of_a_sentence():
    bank = temp_bank()
    bank.observe("Faleminderit shumë për ndihmën.")
    bank.observe("Mirupafshim dhe gjithë të mirat.")
    assert bank.matches("Fal") == ["Faleminderit shumë për ndihmën."]


def test_bank_matching_ignores_case_and_missing_diacritics():
    # The whole point for this user: reaching Ë costs a trip, so typing the
    # plain letters must still find the sentence.
    bank = temp_bank()
    bank.observe("Përshëndetje, si jeni sot?")
    assert bank.matches("pers") == ["Përshëndetje, si jeni sot?"]
    assert bank.matches("PËRSH") == ["Përshëndetje, si jeni sot?"]


def test_bank_does_not_offer_a_sentence_already_fully_typed():
    bank = temp_bank()
    bank.observe("Po vij menjëherë.")
    assert bank.matches("Po vij menjëherë.") == []


def test_bank_ranks_the_used_and_the_recent_first():
    bank = temp_bank()
    bank.observe("Fjalia e vjetër është këtu.")
    for _ in range(3):
        bank.observe("Fjalia e përdorur shpesh.")
    for _ in range(80):                 # push the first one out of recency
        bank.observe("Diçka tjetër krejt.")
    bank.observe("Fjalia e shkruar tani.")
    top = bank.matches("Fjalia", k=3)
    # Just written beats used-three-times-a-while-ago, which beats used once a
    # long time ago. The first of those is the deliberate choice: people repeat
    # what they said a minute ago far more than what they said last month.
    assert top == ["Fjalia e shkruar tani.",
                   "Fjalia e përdorur shpesh.",
                   "Fjalia e vjetër është këtu."]


def test_bank_offers_the_bundled_sentences_before_anything_is_learned():
    bank = temp_bank(builtin=True)
    assert len(bank) == 0
    assert "Faleminderit shumë!" in bank.matches("Fal", k=8)


def test_the_users_own_sentence_outranks_a_bundled_one():
    bank = temp_bank(builtin=True)
    bank.observe("Faleminderit për gjithçka që bëtë.")
    assert bank.matches("Fal", k=8)[0] == "Faleminderit për gjithçka që bëtë."


def test_bank_survives_a_save_and_reload():
    bank = temp_bank()
    bank.observe("Kjo duhet të mbijetojë.")
    bank.save()
    again = SentenceBank(bank.path, builtin=False)
    assert again.matches("") == ["Kjo duhet të mbijetojë."]


def test_bank_clear_removes_the_file_and_the_sentences():
    bank = temp_bank()
    bank.observe("Kjo duhet të fshihet.")
    bank.save()
    bank.clear()
    assert len(bank) == 0
    assert not bank.path.exists()
    assert SentenceBank(bank.path, builtin=False).matches("") == []


def test_engine_learns_a_sentence_when_the_full_stop_arrives():
    e = make_engine()
    e.on_text("Sot jam shumë mirë")
    assert e.bank.matches("") == []      # not finished yet
    e.on_text(".")
    assert e.bank.matches("") == ["Sot jam shumë mirë."]


def test_engine_learns_a_line_ended_by_enter():
    # An address line or a sign-off ends in no punctuation at all, and is
    # exactly the repeated material worth recalling whole.
    e = make_engine()
    e.on_text("Rruga e Dibrës 45, Tiranë\n")
    assert e.bank.matches("") == ["Rruga e Dibrës 45, Tiranë"]


def test_engine_does_not_learn_sentences_when_told_not_to():
    e = make_engine()
    e.learn_sentences = False
    e.on_text("Kjo nuk duhet të ruhet.")
    assert len(e.bank) == 0


def test_engine_reports_the_sentence_being_written():
    e = make_engine()
    e.on_text("Mbaroi kjo. Tani po shkruaj")
    assert e.sentence == "Tani po shkruaj"


def test_engine_offers_sentences_that_continue_the_current_one():
    e = make_engine()
    e.on_text("Do të vij nesër në zyrë.")
    e.on_text(" Do t")
    assert e.sentence_suggestions() == ["Do të vij nesër në zyrë."]


def test_accepting_a_sentence_replaces_only_what_was_typed():
    e = make_engine()
    e.on_text("Faleminderit shumë për ndihmën.")
    e.on_text(" Falem")
    plan = e.plan_sentence("Faleminderit shumë për ndihmën.")
    # An exact prefix is kept rather than deleted and retyped: the backspaces
    # would be real keystrokes travelling to the other application.
    assert plan.backspaces == 0
    assert plan.text == "inderit shumë për ndihmën. "
    assert plan.auto_space


def test_accepting_a_sentence_typed_without_diacritics_retypes_it():
    e = make_engine()
    e.on_text("Përshëndetje nga unë.")
    e.on_text(" Persh")
    plan = e.plan_sentence("Përshëndetje nga unë.")
    # "Persh" is not a prefix of "Përsh", so the accented form has to replace
    # it -- six characters back, then the sentence.
    assert plan.backspaces == 5
    assert plan.text == "Përshëndetje nga unë. "


def test_a_sentence_accepted_from_nothing_is_typed_whole():
    e = make_engine()
    plan = e.plan_sentence("Mirëmëngjes!")
    assert plan.backspaces == 0
    assert plan.text == "Mirëmëngjes! "


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
