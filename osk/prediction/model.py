"""The static Albanian language model: word completion and next-word prediction.

The model is an n-gram table trained offline by ``tools/train.py`` and shipped
as a single compressed file. Two questions are asked of it while typing:

* *completion* -- the user has typed a prefix; which whole words start that way?
* *continuation* -- the user finished a word; which word usually comes next?

Both are answered from one interpolated distribution (see :meth:`context_probs`),
so the two queries can never disagree about what is likely to come next.

**Why interpolation and not stupid backoff.** The first version of this model
took the highest-order n-gram that matched and discarded the rest. On a corpus
this size that is actively harmful: 71% of the trigram contexts were seen with
exactly one continuation, so their conditional probability came out as exactly
1.0 and beat every bigram, however well attested. A trigram observed twice was
overriding a bigram observed a hundred thousand times. Here each order instead
contributes in proportion to how much evidence stands behind it -- a context seen
twice carries a fifth of the weight, a context seen thousands of times carries
essentially all of it -- which is the standard fix and by far the largest single
gain in next-word accuracy.

Two Albanian-specific accommodations are built in:

* **Diacritic-insensitive lookup.** Someone typing with a head pointer or one
  finger should not have to hunt for Ë and Ç to get a suggestion. Typing
  "shqiperi" offers "Shqipëri"; the accented form is still ranked first when the
  user did type the accent.
* **Typo tolerance.** When a prefix yields little, a small set of single-edit
  variants is retried, which recovers the mistaken and doubled keypresses that
  are common with tremor or limited dexterity.
"""

from __future__ import annotations

import bisect
import gzip
import math
import pickle
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .tokens import SENTENCE_START

MODEL_VERSION = 3

#: Evidence needed before a context is trusted outright. A context seen ``K``
#: times is given half the weight of the order below it; the weight then rises
#: towards 1 as the count grows. Trigrams need more evidence than bigrams to earn
#: the same trust because there are so many more of them and each is rarer.
K_TRIGRAM = 8.0
K_BIGRAM = 4.0

#: How many common words are offered alongside whatever the context suggests.
#:
#: This exists to keep the suggestion rows full, not to improve them: measured on
#: held-out Albanian, every value from 0 to 120 scores identically, because a
#: frequent word that the context does not support is correctly ranked below the
#: two dozen continuations the context does support and never reaches a visible
#: row. It earns its place on the days a context is too thin to fill three rows
#: on its own, where the alternative is a blank button.
FREQUENT_FILL = 60

#: How much more common the accented spelling must be before the unaccented one
#: is treated as a misspelling of it rather than as a word in its own right.
#:
#: The corpus separates the two cases with room to spare. Real words that merely
#: look like a stripped-down spelling sit low -- me/më at 1.0x, ne/në at 6.6x --
#: while genuine missing-diacritic errors are outnumbered 10.7x (mire/mirë) to
#: 14.7x (per/për). The bar is set in the gap between those two groups, and
#: deliberately nearer the upper one: hiding a word somebody actually meant is a
#: worse failure than leaving one misspelling in the list.
CANONICAL_RATIO = 8.0

# Ë and Ç are the letters at stake; folding is limited to what Albanian needs
# plus a general NFD pass for anything that slipped into the corpus.
_FOLD_MAP = str.maketrans({"ë": "e", "ç": "c", "Ë": "e", "Ç": "c"})


def fold(word: str) -> str:
    """Lower-case ``word`` and strip the Albanian diacritics."""
    w = word.lower().translate(_FOLD_MAP)
    if any(ord(c) > 127 for c in w):
        w = "".join(c for c in unicodedata.normalize("NFD", w)
                    if not unicodedata.combining(c))
    return w


@dataclass
class Suggestion:
    word: str
    score: float
    source: str = "model"  # model | user | fuzzy

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.word} {self.score:.2f} {self.source}>"


@dataclass
class Context:
    """The probability of any next word, given what came before it.

    Built once per query and asked about many candidate words. Keeping it in one
    object is what lets completion and next-word prediction share a single
    definition of "how likely is this word here" -- when they had one each, a
    word could be ranked first as a completion and nowhere as a continuation.
    """

    model: "LanguageModel"
    p_tri: dict[str, float]
    w_tri: float
    p_bi: dict[str, float]
    w_bi: float
    cache: dict[str, float]
    cache_weight: float
    #: The share of each context's probability its stored list does not account
    #: for. Only the commonest continuations are kept, so a word missing from the
    #: list is not impossible after this context -- it is merely not itemised,
    #: and it has a claim on whatever mass is left over.
    tri_missing: float = 0.0
    bi_missing: float = 0.0

    def attested(self) -> set[str]:
        """Words the context itself has evidence for."""
        return set(self.p_tri) | set(self.p_bi)

    def candidates(self, fill: int = 0) -> set[str]:
        """Words worth scoring: those the context knows, plus a common tail.

        Half of all next words are ordinary vocabulary the n-gram tables happen
        not to list after this particular context. They still have a real
        probability -- the unigram term of the blend -- so they are offered
        rather than excluded, which is most of what fills a second and third row
        of suggestions with something useful.
        """
        words = self.attested() | set(self.cache)
        if fill:
            words |= set(self.model.frequent[:fill])
        return words

    def prob(self, word: str) -> float:
        p_uni = self.model.unigram_prob(word)
        # A word the list does not mention falls back to its share of the mass
        # the list left unaccounted for. Treating it as impossible instead would
        # bury every ordinary word the moment a well-attested context appeared.
        p_bi = self.p_bi.get(word)
        if p_bi is None:
            p_bi = self.bi_missing * p_uni
        p_tri = self.p_tri.get(word)
        if p_tri is None:
            p_tri = self.tri_missing * p_uni

        lower = self.w_bi * p_bi + (1.0 - self.w_bi) * p_uni
        p = self.w_tri * p_tri + (1.0 - self.w_tri) * lower
        if self.cache_weight:
            p = (1.0 - self.cache_weight) * p \
                + self.cache_weight * self.cache.get(word, 0.0)
        return p

    def logp(self, word: str) -> float:
        return math.log(max(self.prob(word), 1e-12))


class LanguageModel:
    """Loaded n-gram tables plus the indexes needed for prefix search."""

    def __init__(self) -> None:
        # Every table is keyed by the lower-cased word, so that "Shqipëri" and
        # "shqipëri" share their statistics. ``surface`` remembers how each word
        # is normally written, which is how proper nouns keep their capital.
        self.unigram: dict[str, int] = {}
        # context -> (times the context was seen, [(continuation, count), ...]).
        # The stored total is the *true* number of occurrences of the context,
        # not the sum of the continuations that survived pruning, so a truncated
        # list cannot inflate the probability of the entries it kept.
        self.bigram: dict[str, tuple[int, list[tuple[str, int]]]] = {}
        self.trigram: dict[str, tuple[int, list[tuple[str, int]]]] = {}
        self.surface: dict[str, str] = {}
        #: Maps a missing-diacritic misspelling onto the correct Albanian word.
        self.canonical: dict[str, str] = {}
        self.total: int = 1
        self.starters: list[tuple[str, int]] = []
        #: Frequent words, used to fill the suggestion rows when the context is
        #: too thin to supply enough candidates of its own.
        self.frequent: list[str] = []
        # Prefix index: folded forms sorted alphabetically, with a parallel list
        # of the original (accented, correctly-cased) words.
        self._folded: list[str] = []
        self._surface: list[str] = []

    # -- loading ----------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "LanguageModel":
        with gzip.open(path, "rb") as fh:
            data = pickle.load(fh)
        if data.get("version") != MODEL_VERSION:
            raise ValueError(
                f"model at {path} has version {data.get('version')}, "
                f"expected {MODEL_VERSION} -- re-run tools/train.py"
            )
        m = cls()
        m.unigram = data["unigram"]
        m.bigram = data["bigram"]
        m.trigram = data["trigram"]
        m.surface = data.get("surface", {})
        m.total = max(1, data["total"])
        m.starters = data.get("starters", [])
        # Building the prefix index means folding every word in the vocabulary
        # twice over, which took two of the four seconds the keyboard used to
        # spend starting up. The trainer does it once instead and ships the
        # result; a model file without it still works, just more slowly.
        index = data.get("index")
        if index:
            m._folded = index["folded"]
            m._surface = index["words"]
            m.canonical = index["canonical"]
            m.frequent = index["frequent"]
        else:
            m._build_index()
        return m

    @classmethod
    def empty(cls) -> "LanguageModel":
        """A model that answers nothing -- used when no model file is present."""
        m = cls()
        m._build_index()
        return m

    def _build_index(self) -> None:
        pairs = sorted((fold(w), w) for w in self.unigram)
        # Where folding changes nothing, reuse the very same string object: the
        # two lists then share their storage instead of doubling it.
        self._folded = [w if f == w else f for f, w in pairs]
        self._surface = [w for _f, w in pairs]
        self.frequent = [w for w, _c in
                         sorted(self.unigram.items(), key=lambda kv: -kv[1])[:400]]
        self._build_canonical()

    def index_payload(self) -> dict:
        """The precomputed index, for the trainer to store alongside the tables."""
        return {"folded": self._folded, "words": self._surface,
                "canonical": self.canonical, "frequent": self.frequent}

    def _build_canonical(self) -> None:
        """Work out which unaccented spellings are simply errors.

        Albanian text on the web is often written without Ë and Ç, so the corpus
        contains both "për" and "per". Suggesting the second to someone learning
        to write faster would be teaching them a misspelling.

        The redirection only ever runs *towards* the accented form, and only when
        that form dominates by :data:`CANONICAL_RATIO`. Real minimal pairs --
        me/më, e/ë -- are nowhere near that ratio and so are left alone, and both
        spellings stay in the vocabulary either way.
        """
        groups: dict[str, list[str]] = defaultdict(list)
        for word in self.unigram:
            groups[fold(word)].append(word)

        self.canonical = {}
        for variants in groups.values():
            if len(variants) < 2:
                continue
            best = max(variants, key=lambda w: self.unigram.get(w, 0))
            if best == fold(best):
                continue  # the dominant spelling carries no diacritics: nothing to fix
            threshold = self.unigram.get(best, 0)
            for variant in variants:
                if variant == best or variant != fold(variant):
                    continue  # only plain-ASCII spellings are candidates for repair
                if self.unigram.get(variant, 0) * CANONICAL_RATIO <= threshold:
                    self.canonical[variant] = best

    def canonicalize(self, word: str) -> str:
        """The correctly-accented spelling of ``word``, if it is a known error."""
        return self.canonical.get(word, word)

    @property
    def vocabulary_size(self) -> int:
        return len(self.unigram)

    def display(self, word: str) -> str:
        """How ``word`` is normally written -- capitalised if it is a proper noun."""
        return self.surface.get(word, word)

    # -- the interpolated distribution -------------------------------------

    def unigram_prob(self, word: str) -> float:
        # Add-half smoothing: an unknown word is unlikely, never impossible.
        return (self.unigram.get(word, 0) + 0.5) / self.total

    def unigram_logp(self, word: str) -> float:
        return math.log(self.unigram_prob(word))

    def context(self, prev1: str = "", prev2: str = "",
                cache: dict[str, float] | None = None,
                cache_weight: float = 0.0) -> "Context":
        """Everything needed to score a next word after ``prev2 prev1``."""
        tri_total, tri = self._table(self.trigram, f"{prev2} {prev1}" if prev2 else "")
        bi_total, bi = self._table(self.bigram, prev1)

        # Weight of each order: 0 with no evidence, 1/2 at K observations, rising
        # towards 1. This is what stops a trigram seen twice from speaking with
        # the authority of one seen ten thousand times.
        w_tri = tri_total / (tri_total + K_TRIGRAM) if tri_total else 0.0
        w_bi = bi_total / (bi_total + K_BIGRAM) if bi_total else 0.0

        p_tri = {w: c / tri_total for w, c in tri} if tri_total else {}
        p_bi = {w: c / bi_total for w, c in bi} if bi_total else {}
        return Context(
            model=self,
            p_tri=p_tri,
            w_tri=w_tri,
            p_bi=p_bi,
            w_bi=w_bi,
            cache=cache or {},
            cache_weight=cache_weight if cache else 0.0,
            tri_missing=max(0.0, 1.0 - sum(p_tri.values())),
            bi_missing=max(0.0, 1.0 - sum(p_bi.values())),
        )

    def context_probs(self, prev1: str = "", prev2: str = "") -> dict[str, float]:
        """P(next word | context) for every word the context has evidence for."""
        ctx = self.context(prev1, prev2)
        return {w: ctx.prob(w) for w in ctx.attested()}

    @staticmethod
    def _table(table: dict[str, tuple[int, list[tuple[str, int]]]],
               key: str) -> tuple[int, list[tuple[str, int]]]:
        if not key:
            return 0, []
        entry = table.get(key)
        if not entry:
            return 0, []
        return entry

    # -- prefix search ----------------------------------------------------

    def words_with_prefix(self, prefix: str, limit: int = 400) -> list[str]:
        """Words whose folded form starts with the folded ``prefix``."""
        if not prefix:
            return []
        key = fold(prefix)
        lo = bisect.bisect_left(self._folded, key)
        hi = bisect.bisect_left(self._folded, key + "￿")
        if hi <= lo:
            return []
        window = self._surface[lo:hi]
        if len(window) > limit:
            window.sort(key=lambda w: -self.unigram.get(w, 0))
            window = window[:limit]
        return window

    def words_equal_folded(self, word: str) -> list[str]:
        """Vocabulary entries that match ``word`` once diacritics are folded away."""
        key = fold(word)
        lo = bisect.bisect_left(self._folded, key)
        hi = bisect.bisect_right(self._folded, key)
        return self._surface[lo:hi]

    def resolve_context(self, word: str) -> str:
        """Map a context word onto the spelling the n-gram tables actually use.

        Albanian is very often typed without its diacritics, so a user who wrote
        "per" or "eshte" would otherwise get no continuations at all. When the
        word as typed has no entry, the accented form it folds to is used
        instead -- which is how "eshte" still predicts what follows "është".
        """
        if not word or word == SENTENCE_START:
            return word
        # "per" predicts poorly because the text that misspells it also misspells
        # what follows; "për" carries the statistics of properly written Albanian.
        word = self.canonicalize(word)
        if word in self.bigram:
            return word
        candidates = [w for w in self.words_equal_folded(word) if w in self.bigram]
        if not candidates:
            return word
        return max(candidates, key=lambda w: self.unigram.get(w, 0))

    def _fuzzy_prefixes(self, prefix: str) -> list[str]:
        """Single-edit variants of ``prefix``, for tremor / mis-hit recovery."""
        variants: list[str] = []
        n = len(prefix)
        if n < 3:
            return variants
        # A doubled or extra keypress: drop one character.
        for i in range(n):
            variants.append(prefix[:i] + prefix[i + 1:])
        # Two keys hit out of order: swap an adjacent pair.
        for i in range(n - 1):
            variants.append(prefix[:i] + prefix[i + 1] + prefix[i] + prefix[i + 2:])
        seen: set[str] = set()
        out = []
        for v in variants:
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out

    # -- the two public queries -------------------------------------------

    def complete(self, prefix: str, prev1: str = "", prev2: str = "",
                 k: int = 8, cache: dict[str, float] | None = None,
                 cache_weight: float = 0.0) -> list[Suggestion]:
        """Rank whole words that begin with ``prefix``, given the words before it."""
        if not prefix:
            return []
        folded_prefix = fold(prefix)
        candidates = self.words_with_prefix(prefix)
        source = "model"
        if len(candidates) < k:
            for variant in self._fuzzy_prefixes(prefix):
                candidates.extend(self.words_with_prefix(variant, limit=40))
                if len(candidates) >= k * 4:
                    break
            source = "fuzzy" if not self.words_with_prefix(prefix) else "model"

        ctx = self.context(prev1, prev2, cache, cache_weight)
        out: list[Suggestion] = []
        seen: set[str] = set()
        for word in candidates:
            if word in seen:
                continue
            seen.add(word)
            # One scale for every candidate, whether the context predicts it or
            # not, so no hand-tuned bonus is needed to trade the two against
            # each other.
            score = ctx.logp(word)
            # Prefer the spelling the user actually typed: an exact prefix match
            # outranks one that only matches after folding away ë/ç.
            if not word.lower().startswith(prefix.lower()):
                score -= 1.2 if fold(word).startswith(folded_prefix) else 3.0
            out.append(Suggestion(word, score, source))
        out.sort(key=lambda s: -s.score)
        return out[:k]

    def next_words(self, prev1: str = "", prev2: str = "", k: int = 8,
                   cache: dict[str, float] | None = None,
                   cache_weight: float = 0.0) -> list[Suggestion]:
        """Predict the word that follows ``prev2 prev1`` (most recent last)."""
        if not prev1:
            pool = self.starters or [(w, self.unigram[w]) for w in self.frequent[:k]]
            return [Suggestion(w, math.log(c + 1), "model") for w, c in pool[:k]]

        ctx = self.context(prev1, prev2, cache, cache_weight)
        scored = [Suggestion(w, ctx.logp(w), "model")
                  for w in ctx.candidates(fill=FREQUENT_FILL)]
        scored.sort(key=lambda s: -s.score)
        return scored[:k]
