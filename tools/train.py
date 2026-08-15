"""Build the Albanian language model shipped with the keyboard.

Usage::

    python tools/train.py --out osk/prediction/data/model_sq.pkl.gz \
        --leipzig corpora/sqi_news_2020_300K.tar.gz \
        --leipzig corpora/sqi_wikipedia_2021_300K.tar.gz \
        --plain   corpora/opensubtitles_sq.txt.gz \
        --freq    corpora/sq_50k.txt \
        --holdout corpora/heldout.txt

Counting trigrams over tens of millions of tokens will exhaust memory if it is
done naively, so the work is split into three passes over a cached, pre-tokenised
copy of the corpus:

1. read every corpus once, tokenise it, write the tokens to a temporary file,
   and count words. The vocabulary is fixed at the end of this pass;
2. count bigrams, over vocabulary words only;
3. count trigrams, over vocabulary words only.

Restricting passes 2 and 3 to the vocabulary is what makes the memory fit: the
overwhelming majority of distinct n-grams involve a word seen once or twice,
and those n-grams would be pruned at the end regardless. Because only one
n-gram table is ever in memory at a time, the caps can be twice what a
single-pass trainer could afford, which is where the extra coverage comes from.

Each context is stored with the *true* number of times it was observed, not the
sum of the continuations that survived pruning. The runtime needs that number
twice over: to avoid inflating the probability of a truncated list, and to know
how far a context is to be trusted at all.
"""

from __future__ import annotations

import argparse
import gzip
import pickle
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osk.prediction.model import MODEL_VERSION, LanguageModel  # noqa: E402
from osk.prediction.tokens import SENTENCE_START, tokenize  # noqa: E402

#: Words eligible to take part in an n-gram. Everything rarer is still offered
#: as a completion -- it stays in the vocabulary -- it simply carries no context
#: statistics, which it could not support anyway.
NGRAM_VOCAB = 120_000

# One table is in memory at a time, so these can be generous. Each entry costs
# roughly 100 bytes, putting the peak near 1.2 GB.
BIGRAM_CAP = 6_000_000
TRIGRAM_CAP = 6_000_000

MIN_UNIGRAM = 3
MIN_NGRAM = 2
#: Enough continuations to fill three rows of suggestions and still leave the
#: ranker something to choose between.
KEEP_PER_BIGRAM_CTX = 24
KEEP_PER_TRIGRAM_CTX = 12
MAX_VOCAB = 250_000

#: Bits per word id when packing an n-gram into a single integer. Integer keys
#: are both smaller and faster to hash than the joined strings they replace.
ID_BITS = 17
assert NGRAM_VOCAB < (1 << ID_BITS)


# -- corpus readers --------------------------------------------------------

def read_leipzig(path: Path):
    """Yield sentences from a Leipzig Corpora ``*.tar.gz`` package."""
    with tarfile.open(path, "r:gz") as tar:
        member = next((m for m in tar.getmembers()
                       if m.name.endswith("-sentences.txt")), None)
        if member is None:
            return
        fh = tar.extractfile(member)
        if fh is None:
            return
        for raw in fh:
            line = raw.decode("utf-8", "replace")
            # Each line is "<id>\t<sentence>".
            _, _, sentence = line.partition("\t")
            if sentence:
                yield sentence.strip()


def read_plain(path: Path):
    """Yield lines from a plain text corpus, gzipped or not."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def read_frequency_list(path: Path) -> dict[str, int]:
    """Read a ``word count`` frequency list (Hermit Dave / OpenSubtitles format)."""
    counts: dict[str, int] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                counts[parts[0].lower()] = int(parts[1])
    return counts


# -- pass 1: tokenise, cache, count words ----------------------------------

def tokenise_corpora(sources, cache: Path, holdout: Path | None,
                     holdout_every: int, max_lines: int):
    """Write every sentence to ``cache`` as lower-case tokens, counting words.

    Every ``holdout_every``-th sentence is diverted to ``holdout`` and never
    trained on, so that accuracy can afterwards be measured on Albanian the model
    has genuinely not seen. Without that, a better score might only mean the
    model had memorised the test.
    """
    uni: dict[str, int] = defaultdict(int)
    surface: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sentences = held = tokens = 0

    hold_fh = open(holdout, "w", encoding="utf-8") if holdout else None
    try:
        with gzip.open(cache, "wt", encoding="utf-8", compresslevel=1) as out:
            for kind, path, reader in sources:
                if not path.exists():
                    print(f"!! missing corpus: {path}", file=sys.stderr)
                    continue
                print(f"reading {kind}: {path.name}", flush=True)
                n = 0
                for sentence in reader(path):
                    words = tokenize(sentence)
                    if len(words) < 2:
                        continue
                    n += 1
                    if hold_fh and holdout_every and n % holdout_every == 0:
                        hold_fh.write(" ".join(words) + "\n")
                        held += 1
                        continue
                    lowered = []
                    for word in words:
                        low = word.lower()
                        lowered.append(low)
                        uni[low] += 1
                        if word != low:
                            surface[low][word] += 1
                    out.write(" ".join(lowered) + "\n")
                    sentences += 1
                    tokens += len(lowered)
                    if sentences % 500_000 == 0:
                        print(f"    {sentences:,} sentences, {tokens:,} tokens, "
                              f"{len(uni):,} words", flush=True)
                    if max_lines and n >= max_lines:
                        break
                print(f"    done: {n:,} sentences", flush=True)
    finally:
        if hold_fh:
            hold_fh.close()

    print(f"  cached {sentences:,} sentences ({tokens:,} tokens), "
          f"held out {held:,}", flush=True)
    return uni, surface, tokens


def read_cache(cache: Path):
    with gzip.open(cache, "rt", encoding="utf-8") as fh:
        for line in fh:
            yield line.split()


# -- passes 2 and 3: n-grams ----------------------------------------------

def prune(table: dict[int, int], floor: int) -> dict[int, int]:
    kept = {k: v for k, v in table.items() if v > floor}
    print(f"    pruned counts <= {floor}: {len(table):,} -> {len(kept):,}", flush=True)
    return kept


def count_bigrams(cache: Path, ids: dict[str, int]):
    """Bigram counts, plus how often each context word was seen as a context."""
    counts: dict[int, int] = defaultdict(int)
    totals: dict[int, int] = defaultdict(int)
    floor = 1
    start = ids[SENTENCE_START]
    for n, words in enumerate(read_cache(cache), 1):
        seq = [start]
        seq.extend(i for i in (ids.get(w, -1) for w in words) if i >= 0)
        for a, b in zip(seq, seq[1:]):
            counts[(a << ID_BITS) | b] += 1
            totals[a] += 1
        if len(counts) > BIGRAM_CAP:
            counts = defaultdict(int, prune(counts, floor))
            floor += 1
        if n % 1_000_000 == 0:
            print(f"    {n:,} sentences, {len(counts):,} bigrams", flush=True)
    return counts, totals


def count_trigrams(cache: Path, ids: dict[str, int]):
    counts: dict[int, int] = defaultdict(int)
    floor = 1
    start = ids[SENTENCE_START]
    for n, words in enumerate(read_cache(cache), 1):
        seq = [start]
        seq.extend(i for i in (ids.get(w, -1) for w in words) if i >= 0)
        for a, b, c in zip(seq, seq[1:], seq[2:]):
            counts[(a << (2 * ID_BITS)) | (b << ID_BITS) | c] += 1
        if len(counts) > TRIGRAM_CAP:
            counts = defaultdict(int, prune(counts, floor))
            floor += 1
        if n % 1_000_000 == 0:
            print(f"    {n:,} sentences, {len(counts):,} trigrams", flush=True)
    return counts


def group(flat: dict[int, int], order: int, words: list[str],
          keep: int, totals: dict[int, int] | None) -> dict[str, tuple[int, list]]:
    """Turn packed n-gram counts into ``{context: (total, [(word, count), ...])}``.

    ``totals`` carries the true number of observations of each context. Where it
    is unavailable the surviving continuations are summed instead, which
    understates the total; that only happens for contexts too rare to have
    survived pruning, and the runtime already distrusts those.
    """
    mask = (1 << ID_BITS) - 1
    grouped: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for packed, count in flat.items():
        if count < MIN_NGRAM:
            continue
        grouped[packed >> ID_BITS].append((words[packed & mask], count))

    out: dict[str, tuple[int, list[tuple[str, int]]]] = {}
    for ctx_id, items in grouped.items():
        items.sort(key=lambda kv: -kv[1])
        items = items[:keep]
        if order == 1:
            context = words[ctx_id]
        else:
            context = f"{words[ctx_id >> ID_BITS]} {words[ctx_id & mask]}"
        total = (totals or {}).get(ctx_id) or sum(c for _, c in items)
        out[context] = (max(total, sum(c for _, c in items)), items)
    return out


def build_index(payload: dict) -> dict:
    """Precompute the runtime's prefix index and misspelling map."""
    model = LanguageModel()
    model.unigram = payload["unigram"]
    model.total = payload["total"]
    model._build_index()
    return model.index_payload()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--leipzig", action="append", type=Path, default=[],
                    help="Leipzig Corpora .tar.gz package (repeatable)")
    ap.add_argument("--plain", action="append", type=Path, default=[],
                    help="plain one-sentence-per-line corpus, .txt or .txt.gz")
    ap.add_argument("--freq", type=Path, default=None,
                    help="word-frequency list used to widen vocabulary coverage")
    ap.add_argument("--holdout", type=Path, default=None,
                    help="write withheld sentences here for tools/evaluate.py")
    ap.add_argument("--holdout-every", type=int, default=200,
                    help="withhold one sentence in N (0 disables)")
    ap.add_argument("--cache", type=Path, default=None,
                    help="where to keep the tokenised corpus (default: temporary)")
    ap.add_argument("--max-lines", type=int, default=0,
                    help="cap lines read per corpus (0 = no cap)")
    args = ap.parse_args()

    sources = [("leipzig", p, read_leipzig) for p in args.leipzig]
    sources += [("plain", p, read_plain) for p in args.plain]

    cache = args.cache or Path(tempfile.gettempdir()) / "osk_tokens.txt.gz"
    cache.parent.mkdir(parents=True, exist_ok=True)

    print("== pass 1: tokenising and counting words", flush=True)
    uni, surface_counts, tokens_seen = tokenise_corpora(
        sources, cache, args.holdout, args.holdout_every, args.max_lines)

    if args.freq and args.freq.exists():
        print(f"reading frequency list: {args.freq.name}", flush=True)
        # Scaled down: it widens coverage of rare words without letting a second
        # count of the same OpenSubtitles data dominate the corpus statistics.
        for word, count in read_frequency_list(args.freq).items():
            uni[word] += max(1, count // 20)

    unigram = {w: c for w, c in uni.items() if c >= MIN_UNIGRAM}
    if len(unigram) > MAX_VOCAB:
        unigram = dict(sorted(unigram.items(), key=lambda kv: -kv[1])[:MAX_VOCAB])
    print(f"  vocabulary: {len(unigram):,}", flush=True)

    # The words allowed into n-grams, and their ids. <s> takes id 0.
    ranked = sorted(unigram.items(), key=lambda kv: -kv[1])[:NGRAM_VOCAB - 1]
    words = [SENTENCE_START] + [w for w, _c in ranked]
    ids = {w: i for i, w in enumerate(words)}
    del ranked

    print("== pass 2: bigrams", flush=True)
    bi_flat, bi_totals = count_bigrams(cache, ids)
    bigram = group(bi_flat, 1, words, KEEP_PER_BIGRAM_CTX, bi_totals)
    del bi_flat, bi_totals
    print(f"  bigram contexts: {len(bigram):,}", flush=True)

    # A trigram context "a b" was observed exactly as often as the bigram "a b",
    # so the counts just built supply the totals for the next pass for free.
    tri_totals: dict[int, int] = {}
    for context, (_total, items) in bigram.items():
        a = ids.get(context)
        if a is None:
            continue
        for word, count in items:
            b = ids.get(word)
            if b is not None:
                tri_totals[(a << ID_BITS) | b] = count

    print("== pass 3: trigrams", flush=True)
    tri_flat = count_trigrams(cache, ids)
    trigram = group(tri_flat, 2, words, KEEP_PER_TRIGRAM_CTX, tri_totals)
    del tri_flat, tri_totals
    print(f"  trigram contexts: {len(trigram):,}", flush=True)

    # A continuation nobody can spell is useless, so drop anything the pruned
    # vocabulary no longer contains. <s> is a context only and never a word.
    def clean(table):
        out = {}
        for context, (total, items) in table.items():
            items = [(w, c) for w, c in items if w in unigram]
            if items:
                out[context] = (total, items)
        return out

    bigram, trigram = clean(bigram), clean(trigram)

    surface = {}
    for word in unigram:
        forms = surface_counts.get(word)
        if forms:
            best = max(forms.items(), key=lambda kv: kv[1])[0]
            # Only a word capitalised more often than not is a proper noun; the
            # rest are merely sentence-initial and must stay lower-case.
            if best != word and forms[best] * 2 > unigram[word]:
                surface[word] = best

    starters = [(w, c) for w, c in bigram.get(SENTENCE_START, (0, []))[1]][:200]

    payload = {
        "version": MODEL_VERSION,
        "unigram": unigram,
        "bigram": bigram,
        "trigram": trigram,
        "surface": surface,
        "starters": starters,
        "total": max(1, sum(unigram.values())),
    }
    # Fold the vocabulary and work out the misspelling map here, once, rather
    # than on every launch: it is two seconds of the keyboard's start-up time.
    print("building the prefix index...", flush=True)
    payload["index"] = build_index(payload)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wb", compresslevel=6) as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

    size_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"\nwrote {args.out}  ({size_mb:.1f} MB)")
    print(f"  vocabulary       {len(unigram):,}")
    print(f"  bigram contexts  {len(bigram):,}")
    print(f"  trigram contexts {len(trigram):,}")
    print(f"  proper nouns     {len(surface):,}")
    print(f"  tokens trained   {tokens_seen:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
