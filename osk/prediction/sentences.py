"""Whole sentences, offered back to the person who wrote them.

Word prediction has a ceiling. Even a perfect next-word model still charges one
press per word, so for somebody typing with one finger it can save a tenth of
the work and no more. The only way past that is to raise the unit of writing
from the word to the sentence -- and a sentence recalled whole costs one press
whether it is four words long or fourteen.

**Why recall and not generation.** The obvious idea is to have the n-gram model
write the sentences. It cannot, and this was measured rather than assumed: a
greedy chain through the shipped model, with the confidence floor swept from
0.40 down to 0.20, produces a three-word run for 1% of contexts and a five-word
run for none of them. Lowering the bar makes it fire more often on the same one
and two word chunks; it does not make the chunks longer. What the model does
produce from a standing start is corpus-average filler -- *nuk e di se çfarë do
të* -- grammatical, and almost never the sentence this user meant. Generation is
therefore left to the phrase feature in engine.py, which bundles the two or
three words the model is genuinely sure of, and the sentence panel is built on
the one source of whole sentences that is reliably right: the ones this person
has already written.

That is not a consolation prize. People repeat themselves enormously -- the
greeting, the sign-off, the sentence about being slow to reply, the address, the
half-dozen answers that make up most of a day's messages. Each of those is
forty-odd presses the first time and one press every time after.

The store is local, capped, and erasable, and it holds the user's own writing,
so it is treated with more care than the word list: sentences carrying long runs
of digits are never recorded, because a card number or a code is exactly the
sort of thing that would otherwise be learned and then offered back on a screen
somebody else can see.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import fold
from .userstore import data_dir

#: Sentences shorter than this are not worth a row: the whole point is to buy
#: back a long trip across the keyboard, and "Po." is already one press.
MIN_WORDS = 2
MIN_CHARS = 6
#: Longer than this is a paragraph that arrived without a full stop, not a
#: sentence, and it would be unreadable on a single row anyway.
MAX_CHARS = 240
#: How many learned sentences to keep. Each is a short string; five hundred of
#: them is a file of perhaps 30 KB, and pruning drops the least useful first.
MAX_SENTENCES = 500

#: Digits in a row that stop a sentence being learned at all. Six is past a year
#: or a house number and into card numbers, codes and telephone numbers -- text
#: that must not be stored and must not reappear on a keyboard in a shared room.
SECRET_DIGITS = re.compile(r"\d{6,}")

#: How much a sentence's most recent use counts for, against how often it has
#: been used. Set so that a sentence just written outranks one used three times
#: a while ago: people write in bursts on one subject, and the sentence they
#: repeat next is far more often the one from a minute ago than the sign-off
#: they used fifty times last month. Two would leave those two cases exactly
#: tied, and a tie at the top of a list read top-down is decided by nothing.
RECENCY_WEIGHT = 3.0
#: Sentences used this long ago (counted in sentences written since) have
#: essentially no recency left.
RECENCY_SPAN = 60.0

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """One-line, single-spaced form of ``text``; "" if it is not a sentence."""
    cleaned = _WS.sub(" ", text.strip())
    if len(cleaned) < MIN_CHARS or len(cleaned) > MAX_CHARS:
        return ""
    if len(cleaned.split()) < MIN_WORDS:
        return ""
    if not any(ch.isalpha() for ch in cleaned):
        return ""
    return cleaned


def learnable(text: str) -> bool:
    """Whether a sentence may be written to disk at all."""
    return bool(text) and not SECRET_DIGITS.search(text)


#: Everyday Albanian sentences, so the panel is useful on the first day rather
#: than only after weeks of writing. They are ranked below anything the user has
#: actually written and drop away as their own sentences arrive.
#:
#: The order is the ranking, and it is ordered by what a sentence is *worth* to
#: somebody typing with one finger -- roughly how often it is needed multiplied
#: by how long it takes to type -- not alphabetically and not by length. The
#: sentences that ask for help and buy time come first: they are the ones this
#: keyboard exists for, they are long, and they are needed most urgently at
#: exactly the moment typing them out is least possible.
BUILTIN = [
    "Po shkruaj ngadalë, ju lutem kini durim.",
    "A mund të më ndihmoni, ju lutem?",
    "Kam nevojë për ndihmë.",
    "Ju lutem, prisni një moment.",
    "Do t'ju kthej përgjigje sa më shpejt.",
    "Do të përgjigjem më vonë.",
    "Faleminderit shumë!",
    "Përshëndetje, si jeni?",
    "Mirë jam, faleminderit.",
    "Ju faleminderit për mesazhin.",
    "E mora mesazhin tuaj.",
    "Në rregull, faleminderit.",
    "E kuptova, faleminderit.",
    "Më falni, nuk kuptova.",
    "A mund ta përsërisni, ju lutem?",
    "A mund të flasim më vonë?",
    "Po, jam dakord.",
    "Jo, nuk jam dakord.",
    "Nuk jam i sigurt.",
    "Nuk e di ende.",
    "Sot nuk mundem.",
    "Nesër jam i lirë.",
    "Po, në rregull.",
    "Jo, faleminderit.",
    "Ju lutem.",
    "Përshëndetje!",
    "Mirëmëngjes!",
    "Mirëdita!",
    "Mirëmbrëma!",
    "Si jeni?",
    "Si je?",
    "Ju uroj një ditë të mirë!",
    "Shihemi më vonë.",
    "Mirupafshim!",
    "Natën e mirë!",
    "Gjithë të mirat,",
    "Me respekt,",
]


@dataclass
class Sentence:
    text: str
    count: float
    last: int
    builtin: bool = False
    #: Position in :data:`BUILTIN`, which is a curated ranking; 0 for anything
    #: the user wrote, where the count and the recency decide instead.
    order: int = 0


class SentenceBank:
    """The sentences this user writes, ranked for the moment they are in.

    Two sources, one list. Anything the user has written outranks anything
    bundled, because the bundled set exists only to keep the panel from being
    empty before there is a history to draw on.
    """

    def __init__(self, path: Path | None = None, builtin: bool = True) -> None:
        self.path = path or (data_dir() / "sentences.json")
        self.learned: dict[str, Sentence] = {}
        #: Sentences written, ever. Used as the clock for recency, so that no
        #: wall-clock time is stored and the ranking is reproducible in a test.
        self.clock = 0
        self._dirty = False
        self._builtin: dict[str, Sentence] = {}
        if builtin:
            self._builtin = {
                fold(text): Sentence(text, 0.0, 0, builtin=True, order=index)
                for index, text in enumerate(BUILTIN)
            }
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("sentences", []):
            try:
                text = normalise(str(row["text"]))
                if not text:
                    continue
                self.learned[fold(text)] = Sentence(
                    text, float(row.get("count", 1.0)), int(row.get("last", 0)))
            except (KeyError, TypeError, ValueError):
                continue
        self.clock = int(data.get("clock", len(self.learned)))

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {
            "clock": self.clock,
            "sentences": [{"text": s.text, "count": s.count, "last": s.last}
                          for s in self.learned.values()],
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def clear(self) -> None:
        self.learned.clear()
        self.clock = 0
        self._dirty = True
        self.save()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    # -- learning ----------------------------------------------------------

    def observe(self, text: str) -> bool:
        """Record a finished sentence. Returns whether it was kept."""
        text = normalise(text)
        if not learnable(text):
            return False
        self.clock += 1
        key = fold(text)
        entry = self.learned.get(key)
        if entry is None:
            # Keep the spelling of the newest version: if the user went back and
            # added the accents, that is the form they want offered.
            self.learned[key] = Sentence(text, 1.0, self.clock)
        else:
            entry.count += 1.0
            entry.last = self.clock
            entry.text = text
        self._dirty = True
        if len(self.learned) > MAX_SENTENCES:
            self._prune()
        return True

    def forget(self, text: str) -> None:
        """Drop one sentence, for a mistake the user does not want offered again."""
        if self.learned.pop(fold(text), None) is not None:
            self._dirty = True

    def _prune(self) -> None:
        """Drop the least useful sentences, keeping the store at its cap."""
        ranked = sorted(self.learned.items(),
                        key=lambda kv: -self._score(kv[1]))
        self.learned = dict(ranked[:MAX_SENTENCES])

    # -- ranking -----------------------------------------------------------

    def _score(self, entry: Sentence) -> float:
        """How strongly to offer ``entry`` right now.

        Frequency and recency, plus a flat penalty for the bundled set so that
        a sentence the user has actually written always comes first.
        """
        if entry.builtin:
            return -1.0
        age = max(0, self.clock - entry.last)
        recency = max(0.0, 1.0 - age / RECENCY_SPAN)
        return entry.count + RECENCY_WEIGHT * recency

    def _pool(self) -> dict[str, Sentence]:
        """Every sentence on offer, the user's own shadowing the bundled ones.

        Keyed by the folded text, which is what :meth:`matches` compares
        against. Both stores are already keyed that way, so prefix matching
        costs no folding at all -- and it is done on every keystroke, over a
        store of up to five hundred sentences, which is the difference between
        0.3 ms and 5 ms of lag behind every letter.
        """
        pool = dict(self._builtin)
        pool.update(self.learned)
        return pool

    def matches(self, typed: str = "", k: int = 6) -> list[str]:
        """Sentences that continue what has been typed so far, best first.

        ``typed`` is the part of the current sentence already written. Matching
        folds away Ë and Ç and ignores case, so somebody who cannot easily reach
        the accented letters still finds their own sentence -- and it matches on
        the sentence's opening, which turns the first two or three letters into
        a shortcut for the whole thing.
        """
        needle = fold(_WS.sub(" ", typed.strip()))
        hits = []
        for folded, entry in self._pool().items():
            if needle and not folded.startswith(needle):
                continue
            if needle and len(entry.text) <= len(typed):
                continue    # nothing left to add
            hits.append(entry)
        # Ties are broken by the curated order, then by length -- longest
        # first, because two sentences equally likely to be wanted are not
        # equally worth a row: the long one buys back more of the trip.
        hits.sort(key=lambda e: (-self._score(e), e.order, -len(e.text)))
        return [e.text for e in hits[:k]]

    def builtin_texts(self) -> list[str]:
        """The bundled everyday sentences, for the Options dialog to count."""
        return [e.text for e in self._builtin.values()]

    def all_learned(self) -> list[str]:
        """Every sentence the user has written, best first -- for the editor."""
        ranked = sorted(self.learned.values(), key=lambda e: -self._score(e))
        return [e.text for e in ranked]

    def __len__(self) -> int:
        return len(self.learned)
