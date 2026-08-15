"""The part of the language model that learns from this particular user.

A shipped corpus knows Albanian in general; it does not know the user's name,
their town, their doctor, or the three phrases they type every day. For someone
who types slowly, those personal words are exactly where prediction saves the
most effort, so every committed word is folded back into a private model held
alongside the static one.

The store is deliberately small and local: a JSON file under %APPDATA%, never
transmitted anywhere, capped in size, and erasable from the Options dialog.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / "ShqipKeyboard"
    path.mkdir(parents=True, exist_ok=True)
    return path


class UserModel:
    """Adaptive unigram + bigram counts for one user."""

    MAX_UNIGRAMS = 20_000
    MAX_BIGRAM_CONTEXTS = 20_000
    #: Counts are halved once the store grows past its cap, so that vocabulary
    #: the user has stopped using fades instead of competing forever.
    DECAY = 0.5

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "user_model.json")
        self.unigram: dict[str, float] = {}
        self.bigram: dict[str, dict[str, float]] = {}
        self.total: float = 0.0
        self._dirty = False
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        try:
            # utf-8-sig tolerates a byte-order mark, so a store that has been
            # opened and re-saved by another tool still loads.
            with open(self.path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        self.unigram = {str(k): float(v) for k, v in data.get("unigram", {}).items()}
        self.bigram = {
            str(k): {str(w): float(c) for w, c in v.items()}
            for k, v in data.get("bigram", {}).items()
        }
        self.total = float(data.get("total", sum(self.unigram.values())))

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {"unigram": self.unigram, "bigram": self.bigram, "total": self.total}
        # Write via a temporary file so a crash mid-save cannot corrupt the
        # user's accumulated vocabulary.
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
        self.unigram.clear()
        self.bigram.clear()
        self.total = 0.0
        self._dirty = True
        self.save()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    # -- learning ----------------------------------------------------------

    def observe(self, word: str, prev: str = "") -> None:
        """Record that the user wrote ``word`` after ``prev``."""
        if not word or not word[0].isalpha():
            return
        self.unigram[word] = self.unigram.get(word, 0.0) + 1.0
        self.total += 1.0
        if prev:
            self.bigram.setdefault(prev, {})
            ctx = self.bigram[prev]
            ctx[word] = ctx.get(word, 0.0) + 1.0
        self._dirty = True
        if len(self.unigram) > self.MAX_UNIGRAMS or len(self.bigram) > self.MAX_BIGRAM_CONTEXTS:
            self._prune()

    def _prune(self) -> None:
        for word in list(self.unigram):
            self.unigram[word] *= self.DECAY
            if self.unigram[word] < 0.5:
                del self.unigram[word]
        self.total = sum(self.unigram.values())
        for ctx in list(self.bigram):
            table = self.bigram[ctx]
            for word in list(table):
                table[word] *= self.DECAY
                if table[word] < 0.5:
                    del table[word]
            if not table:
                del self.bigram[ctx]

    # -- querying ----------------------------------------------------------

    def boost(self, word: str, prev: str = "") -> float:
        """Additive log-space bonus for ``word``; 0.0 when the user never used it."""
        bonus = 0.0
        count = self.unigram.get(word, 0.0)
        if count:
            bonus += 0.9 * math.log1p(count)
        if prev:
            ctx = self.bigram.get(prev)
            if ctx and word in ctx:
                bonus += 1.6 * math.log1p(ctx[word])
        return bonus

    def words_with_prefix(self, prefix_folded: str, fold_fn, limit: int = 40) -> list[str]:
        """User words matching a folded prefix (the store is small; scan it)."""
        if not prefix_folded:
            return []
        hits = [w for w in self.unigram if fold_fn(w).startswith(prefix_folded)]
        hits.sort(key=lambda w: -self.unigram[w])
        return hits[:limit]

    def next_words(self, prev: str, limit: int = 8) -> list[tuple[str, float]]:
        ctx = self.bigram.get(prev)
        if not ctx:
            return []
        items = sorted(ctx.items(), key=lambda kv: -kv[1])[:limit]
        return items
