"""
Pure text helpers for Thai-aware word splitting and ASR output cleanup.

Kept dependency-free (PyThaiNLP imported lazily) so unit tests can run on
host machines without the heavy ASR stack.
"""

import re

# Thai grapheme ranges (Unicode): consonants, vowels, tone marks, and digits.
_THAI_CHARS = r"\u0E00-\u0E7F"
_WHITESPACE_RE = re.compile(r"\s+")


def collapse_repeated_tokens(tokens: list, max_repeat: int = 3) -> list:
    """
    Collapse pathological consecutive repetitions produced by RNNT decode loops.

    NeMo FastConformer-Transducer (Typhoon) occasionally enters a decode loop
    and repeats a single token dozens of times (e.g. "นาง" x41). These loops
    are pure hallucination and pollute both the raw text and the proportional
    timestamps used for speaker merging. This keeps at most ``max_repeat``
    consecutive identical tokens, preserving legitimate short emphasis
    ("เร็วเร็ว", "ไม่ไม่") while killing long loops.
    """
    if not tokens:
        return tokens
    collapsed: list = []
    for tok in tokens:
        run_len = 0
        for prev in reversed(collapsed):
            if prev == tok:
                run_len += 1
            else:
                break
        if run_len >= max_repeat:
            continue
        collapsed.append(tok)
    return collapsed


def split_into_words(text: str) -> list:
    """
    Tokenize transcription text into words/units suitable for building
    proportional timestamps.

    Thai text rarely contains spaces, so ``str.split()`` collapses a whole
    sentence into one giant token (which makes speaker-diariazation merges
    useless). Prefer PyThaiNLP when installed; otherwise fall back to a
    whitespace + Thai-character-run splitter so every chunk yields several
    small units.
    """
    if not text:
        return []

    try:
        from pythainlp.tokenize import word_tokenize

        tokens = word_tokenize(text, engine="newmm")
        tokens = [t for t in tokens if t.strip()]
        if tokens:
            return collapse_repeated_tokens(tokens)
    except Exception:
        pass

    # Fallback: split on whitespace first, then further split any Thai-only
    # run into ~2-char pseudo-words (preserves text when rejoined with '').
    words: list = []
    for token in _WHITESPACE_RE.split(text):
        if not token:
            continue
        if any(ord(ch) >= 0x0E00 and ord(ch) <= 0x0E7F for ch in token):
            for i in range(0, len(token), 2):
                piece = token[i : i + 2]
                if piece:
                    words.append(piece)
        else:
            words.append(token)
    return collapse_repeated_tokens(words)


def clean_text(text: str) -> str:
    """
    Remove RNNT decode-loop hallucinations from raw ASR text.

    Uses the same tokenization as ``split_into_words`` (which collapses
    pathological repeats) and rejoins into a single string. Thai runs are
    rejoined with '' to preserve the original no-space appearance; other
    languages keep space-separated words.
    """
    words = split_into_words(text)
    if not words:
        return text
    if any(ord(ch) >= 0x0E00 and ord(ch) <= 0x0E7F for ch in "".join(words)):
        return "".join(words)
    return " ".join(words)
