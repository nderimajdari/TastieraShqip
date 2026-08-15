"""Ties the language model, the user model and the typing context together.

The engine keeps a shadow copy of the recent text so it knows what has been
written without reading the target application's contents. That buffer is fed by
the keys this keyboard sends, and it is cleared whenever focus moves to another
window -- at that point the old context no longer describes what the caret sits
in front of, and stale context produces worse predictions than none.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import LanguageModel, fold
from .tokens import (
    at_sentence_start, context_words, match_case, trailing_prefix,
)
from .userstore import UserModel

#: How much recent text to remember. Two sentences is plenty for a trigram
#: model and keeps the shadow buffer from growing without bound.
CONTEXT_CHARS = 300

#: How much of the prediction is given over to what the user has written lately.
#: Measured on held-out Albanian read as one stream; 0.2 was the best value for
#: the first and seventh suggestion, which is where most selections are made.
#: The measurement understates it, because those held-out sentences come from all
#: over the corpora and share no subject, whereas a real message or document does.
CACHE_WEIGHT = 0.2


class RecencyCache:
    """The words this user has written lately.

    About half the time the n-gram tables have nothing to say about the next
    word -- it is ordinary vocabulary that simply never followed this particular
    context in the corpus. Repetition is the signal still available: people write
    about one thing at a time and reuse its words, and a name or a diagnosis or a
    place that has just been typed is far more likely to be typed again than its
    corpus frequency suggests.

    Counts decay with every word written, so the subject can change without the
    old vocabulary lingering.
    """

    DECAY = 0.995
    FLOOR = 0.02
    MAX_WORDS = 400
    #: Words that must be in the cache before it is trusted at full strength.
    #: Without this, the first word of a session is the whole of the cache and
    #: is offered as though it were half the language.
    CONFIDENCE = 12.0

    def __init__(self) -> None:
        self._counts: dict[str, float] = {}
        self._total = 0.0

    def observe(self, word: str) -> None:
        if not word:
            return
        for known in list(self._counts):
            self._counts[known] *= self.DECAY
            if self._counts[known] < self.FLOOR:
                del self._counts[known]
        self._counts[word] = self._counts.get(word, 0.0) + 1.0
        if len(self._counts) > self.MAX_WORDS:
            for known, _c in sorted(self._counts.items(), key=lambda kv: kv[1]
                                    )[:len(self._counts) - self.MAX_WORDS]:
                del self._counts[known]
        self._total = sum(self._counts.values())

    def probs(self) -> dict[str, float]:
        """The cache as a distribution, ready to blend with the model's."""
        if not self._total:
            return {}
        return {w: c / self._total for w, c in self._counts.items()}

    def weight(self, full: float) -> float:
        """How much of the prediction this cache has earned, up to ``full``."""
        if not self._total:
            return 0.0
        return full * self._total / (self._total + self.CONFIDENCE)

    def clear(self) -> None:
        self._counts.clear()
        self._total = 0.0


@dataclass
class AcceptPlan:
    """How to turn the half-typed word into the accepted one.

    Suggestions are not always extensions of what was typed -- a diacritic-blind
    or typo-tolerant match replaces it -- so accepting is expressed as "delete
    this many characters, then type this text".
    """

    backspaces: int
    text: str


class PredictionEngine:
    def __init__(self, model_path: str | Path | None = None,
                 user_model: UserModel | None = None) -> None:
        self.model = LanguageModel.empty()
        self.model_error: str | None = None
        if model_path and Path(model_path).exists():
            try:
                self.model = LanguageModel.load(model_path)
            except Exception as exc:  # a broken model must not stop the keyboard
                self.model_error = str(exc)
        self.user = user_model if user_model is not None else UserModel()
        self._buffer = ""
        self.auto_space = True
        self.learn = True
        # Survives a focus change deliberately: the shadow buffer describes one
        # caret and stops being true the moment it moves, but the subject a
        # person is writing about carries across windows -- the reply, the note
        # about it, the search for the same name.
        self.recent = RecencyCache()

    def attach_model(self, model: LanguageModel) -> None:
        """Install a model loaded elsewhere -- see :class:`ModelLoader`.

        Until this is called the engine answers from an empty model, which is
        what lets the keyboard open and be typed on immediately instead of making
        the user wait several seconds for a dictionary they may not need yet.
        """
        self.model = model
        self.model_error = None

    # -- context tracking --------------------------------------------------

    @property
    def buffer(self) -> str:
        return self._buffer

    def reset(self) -> None:
        """Forget the current context (call when focus leaves the app)."""
        self._buffer = ""

    def on_text(self, text: str) -> None:
        """Record characters that were just typed into the target application."""
        for ch in text:
            self._buffer += ch
            if not ch.isalnum() and ch not in "'’-":
                self._commit_last_word()
        if len(self._buffer) > CONTEXT_CHARS * 2:
            self._buffer = self._buffer[-CONTEXT_CHARS:]

    def on_backspace(self, count: int = 1) -> None:
        if count >= len(self._buffer):
            # We cannot see past the start of our own buffer, so anything beyond
            # it is unknown text; drop the context rather than guess.
            self._buffer = ""
        else:
            self._buffer = self._buffer[:-count]

    def on_navigation(self) -> None:
        """Arrow keys, clicks and the like move the caret somewhere we cannot see."""
        self.reset()

    def _commit_last_word(self) -> None:
        """Note the word that was just finished, and what preceded it."""
        # Drop the separator that ended the word, then read the sentence it
        # belongs to. A word that opened a sentence is learned against the
        # sentence-start marker, so the phrases somebody habitually begins with
        # are predicted the moment they finish the previous sentence.
        tail = self._buffer.rstrip()
        while tail and not (tail[-1].isalnum() or tail[-1] in "'’-"):
            tail = tail[:-1]
        words = context_words(tail)
        if len(words) < 2:
            return
        # The cache tracks the subject at hand and is not a record of anything,
        # so it fills up whether or not the user wants words remembered between
        # sessions. Only the persistent store obeys that setting.
        self.recent.observe(words[-1].lower())
        if self.learn:
            self.user.observe(words[-1].lower(), words[-2].lower())

    # -- queries -----------------------------------------------------------

    @property
    def prefix(self) -> str:
        return trailing_prefix(self._buffer)

    def _previous_words(self) -> tuple[str, str]:
        """The one or two words the prediction is conditioned on.

        The context stops at the last full stop and begins with a sentence-start
        marker, so that after "Shkova në shtëpi. " the model is asked what opens
        a sentence rather than what tends to follow "shtëpi" -- which is a
        question about the previous sentence and no help with the next one.
        """
        words = context_words(self._buffer)
        if self.prefix and len(words) > 1:
            words = words[:-1]
        prev1 = words[-1].lower() if words else ""
        prev2 = words[-2].lower() if len(words) >= 2 else ""
        # Undiacriticised input still has to find its n-grams.
        return self.model.resolve_context(prev1), self.model.resolve_context(prev2)

    def suggestions(self, k: int = 8) -> list[str]:
        """Ranked words to offer right now.

        With a partial word this completes it; immediately after a space it
        predicts the next word outright, which is where most of the keystroke
        saving for a slow typist comes from.
        """
        prefix = self.prefix
        prev1, prev2 = self._previous_words()

        if prefix:
            # No recency here. Once letters have been typed they are far stronger
            # evidence than what was written a moment ago, and blending recency
            # in measurably cost both completion accuracy and keystrokes saved.
            base = self.model.complete(prefix, prev1, prev2, k=k * 3)
            merged = {s.word: s.score for s in base}
            for word in self.user.words_with_prefix(fold(prefix), fold):
                merged.setdefault(word, self.model.unigram_logp(word))
            for word in list(merged):
                merged[word] += self.user.boost(word, prev1)
        else:
            base = self.model.next_words(
                prev1, prev2, k=k * 3, cache=self.recent.probs(),
                cache_weight=self.recent.weight(CACHE_WEIGHT))
            merged = {s.word: s.score for s in base}
            for word, count in self.user.next_words(prev1, limit=k):
                merged[word] = merged.get(word, self.model.unigram_logp(word))
            for word in list(merged):
                merged[word] += self.user.boost(word, prev1)

        ranked = sorted(merged.items(), key=lambda kv: -kv[1])
        capitalise = at_sentence_start(self._buffer[: len(self._buffer) - len(prefix)])

        out: list[str] = []
        seen: set[str] = set()
        for word, _score in ranked:
            # Offer the correctly-accented spelling, never a known misspelling.
            word = self.model.canonicalize(word)
            display = self.model.display(word)
            shown = display
            if prefix:
                if len(prefix) > 1 and prefix.isupper():
                    shown = display.upper()
                elif not display[:1].isupper():
                    # Not a proper noun, so follow the user's own capitalisation.
                    shown = match_case(prefix, display)
            elif capitalise:
                shown = shown[:1].upper() + shown[1:]
            if shown.lower() in seen:
                continue
            seen.add(shown.lower())
            out.append(shown)
            if len(out) >= k:
                break
        return out

    # -- accepting ---------------------------------------------------------

    def plan_accept(self, word: str) -> AcceptPlan:
        """Work out the edit that replaces the half-typed word with ``word``."""
        prefix = self.prefix
        tail = " " if self.auto_space else ""
        if prefix and word.lower().startswith(prefix.lower()):
            return AcceptPlan(0, word[len(prefix):] + tail)
        return AcceptPlan(len(prefix), word + tail)

    def flush(self) -> None:
        self.user.save()
