"""Measure prediction accuracy on Albanian the model was not trained on.

Usage::

    python tools/evaluate.py --model osk/prediction/data/model_sq.pkl.gz \
        --holdout corpora/heldout.txt

Two things are measured, because they are what the keyboard actually offers:

* **next word** -- given the sentence so far, is the following word among the
  suggestions? Reported at ranks 1, 3, 7 and 21, matching one, one row, and
  three rows of buttons.
* **completion** -- after typing the first letter or two of a word, is the whole
  word offered? This is where the keystrokes are saved.

Also reported is *keystrokes saved*: the share of characters the user would not
have to press if they accepted the best offer available at every point. That is
the number that matters to somebody typing with one finger or a head pointer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osk.prediction.engine import CACHE_WEIGHT, RecencyCache  # noqa: E402
from osk.prediction.model import LanguageModel  # noqa: E402
from osk.prediction.tokens import SENTENCE_START  # noqa: E402

RANKS = (1, 3, 7, 21)


def evaluate(model: LanguageModel, sentences, prefix_len: int = 2, limit: int = 0,
             cache_weight: float = CACHE_WEIGHT):
    """Score ``sentences`` as one continuous stream.

    A stream, not a set of independent sentences, because that is what the
    keyboard sees and it is the only way the recency cache is exercised at all.
    It still understates the cache: consecutive held-out sentences are drawn from
    all over the corpora and share no subject, where a real document does.

    The cache applies to next-word prediction only, exactly as the keyboard uses
    it -- mixing recency into completions was measured and made them worse.
    """
    next_hits = {r: 0 for r in RANKS}
    comp_hits = {r: 0 for r in RANKS}
    next_total = comp_total = 0
    typed = saved = 0
    recent = RecencyCache()

    for n, words in enumerate(sentences, 1):
        if limit and n > limit:
            break
        history = [SENTENCE_START]
        for word in words:
            target = word.lower()
            prev1 = model.resolve_context(history[-1])
            prev2 = model.resolve_context(history[-2]) if len(history) >= 2 else ""
            cache = recent.probs() if cache_weight else None

            ranked = [s.word for s in model.next_words(
                prev1, prev2, k=max(RANKS), cache=cache,
                cache_weight=recent.weight(cache_weight))]
            next_total += 1
            best_rank = None
            for r in RANKS:
                if target in ranked[:r]:
                    next_hits[r] += 1
                    best_rank = best_rank or r

            # Keystrokes: either the word was offered outright (one press), or it
            # is typed until a completion appears (that many presses, plus one).
            cost = len(target) + 1  # the word, then a space
            if best_rank is not None and best_rank <= 7:
                spent = 1
            else:
                spent = cost
                for i in range(1, len(target)):
                    offered = [s.word for s in model.complete(
                        target[:i], prev1, prev2, k=7)]
                    if target in offered:
                        spent = i + 1
                        break
            typed += cost
            saved += max(0, cost - spent)

            if len(target) > prefix_len:
                offered = [s.word for s in model.complete(
                    target[:prefix_len], prev1, prev2, k=max(RANKS))]
                comp_total += 1
                for r in RANKS:
                    if target in offered[:r]:
                        comp_hits[r] += 1

            history.append(target)
            recent.observe(target)
    return next_hits, next_total, comp_hits, comp_total, typed, saved


def read_holdout(path: Path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            words = line.split()
            if len(words) >= 2:
                yield words


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, type=Path)
    ap.add_argument("--holdout", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=3000,
                    help="sentences to score (0 = all)")
    ap.add_argument("--prefix", type=int, default=2,
                    help="letters typed before asking for a completion")
    ap.add_argument("--no-cache", action="store_true",
                    help="score without the recency cache, to isolate its effect")
    args = ap.parse_args()

    model = LanguageModel.load(args.model)
    print(f"model {args.model.name}: {model.vocabulary_size:,} words, "
          f"{len(model.bigram):,} bigram / {len(model.trigram):,} trigram contexts\n")

    nh, nt, ch, ct, typed, saved = evaluate(
        model, read_holdout(args.holdout), args.prefix, args.limit,
        cache_weight=0.0 if args.no_cache else CACHE_WEIGHT)

    print(f"next word          ({nt:,} predictions)")
    for r in RANKS:
        print(f"   top-{r:<3} {100 * nh[r] / max(1, nt):6.2f}%")
    print(f"\ncompletion after {args.prefix} letters   ({ct:,} words)")
    for r in RANKS:
        print(f"   top-{r:<3} {100 * ch[r] / max(1, ct):6.2f}%")
    print(f"\nkeystrokes saved   {100 * saved / max(1, typed):6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
