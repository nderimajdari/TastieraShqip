"""Tokenisation shared by the trainer and the running keyboard.

The trainer and the predictor must agree on what a word is, or every lookup
misses. Keeping the rules in one module is what guarantees that.

Albanian specifics: Ë and Ç are word characters, and the apostrophe is kept
inside words so forms like "s'ka" stay whole.
"""

from __future__ import annotations

import re

WORD_CHARS = r"a-zA-ZçëíáéóúüàèòùÀ-ɏ"

#: A word: letters, optionally with internal apostrophes or hyphens.
WORD_RE = re.compile(rf"[{WORD_CHARS}]+(?:['’\-][{WORD_CHARS}]+)*")

#: The trailing partial word at the caret, used to drive completion.
TRAILING_RE = re.compile(rf"[{WORD_CHARS}]+(?:['’\-][{WORD_CHARS}]*)*$")

SENTENCE_BREAK_RE = re.compile(r"[.!?…]+[\s\"')\]]*$")

#: Splits a buffer at the last sentence ending, so the context used for
#: prediction stops at the full stop instead of reaching back into the previous
#: sentence, where the words have no bearing on what comes next.
SENTENCE_TAIL_RE = re.compile(r"[.!?…]+[\s\"')\]]*(?=[^.!?…]*$)")

#: Marks the start of a sentence. Counted by the trainer as an ordinary context
#: word, so that "what opens a sentence" is answered by the same tables as every
#: other prediction. It is never a continuation and never enters the vocabulary.
SENTENCE_START = "<s>"


def tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text)


def trailing_prefix(text: str) -> str:
    """The unfinished word at the end of ``text`` (empty after a separator)."""
    m = TRAILING_RE.search(text)
    return m.group(0) if m else ""


def at_sentence_start(text: str) -> bool:
    """True when the next word begins a sentence (or the buffer is empty)."""
    stripped = text.rstrip()
    if not stripped:
        return True
    return bool(SENTENCE_BREAK_RE.search(stripped))


def current_sentence(text: str) -> str:
    """The part of ``text`` belonging to the sentence still being written."""
    last = None
    for last in SENTENCE_TAIL_RE.finditer(text):
        pass
    return text[last.end():] if last else text


def context_words(text: str) -> list[str]:
    """Words of the current sentence, opened by :data:`SENTENCE_START`.

    Prediction reads the last one or two entries of this list. Cutting at the
    sentence boundary matters: after "Shkova në shtëpi. " the useful question is
    what usually *starts* a sentence, not what usually follows "shtëpi".
    """
    return [SENTENCE_START] + tokenize(current_sentence(text))


def match_case(source: str, target: str) -> str:
    """Apply the capitalisation the user started typing to a suggestion.

    Typing "sh" offers "shqip"; typing "Sh" offers "Shqip"; typing "SH" offers
    "SHQIP". Without this, accepting a prediction would silently undo the
    capital the user deliberately typed.
    """
    if not source:
        return target
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[0].isupper():
        return target[0].upper() + target[1:]
    return target
