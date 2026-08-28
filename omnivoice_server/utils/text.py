"""
Sentence splitting for streaming mode.

Goal: Split text into chunks that:
  1. End at natural sentence boundaries (. ! ? newline)
  2. Don't exceed max_chars
  3. Don't split in the middle of numbers, abbreviations, URLs
"""

from __future__ import annotations

import re

# Non-verbal symbols OmniVoice recognises inline in text. Anything else in
# square brackets is passed to the model as literal text, which is how a typo
# like [laugh] turns into unpredictable output rather than an error (issue #37).
NONVERBAL_TAGS = frozenset(
    {
        "laughter",
        "breath",
        "sigh",
        "sniff",
        "confirmation-en",
        "question-en",
        "question-ah",
        "question-oh",
        "question-ei",
        "question-yi",
        "surprise-ah",
        "surprise-oh",
        "surprise-wa",
        "surprise-yo",
        "dissatisfaction-hnn",
    }
)

# Deliberately permissive: matches anything bracketed so unknown tags can be
# reported. Pronunciation hints use a different syntax and are not matched here.
_BRACKETED = re.compile(r"\[([a-zA-Z][a-zA-Z0-9_-]*)\]")


def find_nonverbal_tags(text: str) -> list[str]:
    """Return every bracketed tag in `text`, in order, including unknown ones."""
    if not text:
        return []
    return [m.group(1).lower() for m in _BRACKETED.finditer(text)]


def count_nonverbal_tags(text: str) -> int:
    """Number of recognised non-verbal tags in `text`."""
    return sum(1 for tag in find_nonverbal_tags(text) if tag in NONVERBAL_TAGS)


def find_unknown_nonverbal_tags(text: str) -> list[str]:
    """
    Bracketed tokens that look like non-verbal tags but are not recognised.

    Deduplicated, order preserved, so the caller can name them all in one
    warning rather than one per occurrence.
    """
    seen: dict[str, None] = {}
    for tag in find_nonverbal_tags(text):
        if tag not in NONVERBAL_TAGS:
            seen.setdefault(tag, None)
    return list(seen)

# Split at sentence boundaries: period/exclamation/question followed by space and capital letter
# Also split at Chinese/Japanese sentence endings
_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff\u3040-\u30ff\u00C0-\u024F\u1E00-\u1EFF])"
    r"|(?<=[。！？])"
)

# Patterns that should NOT be treated as sentence boundaries
_FALSE_ENDS = re.compile(
    r"\d+\.\d+"  # Decimals: 3.14
    r"|v\d+\.\d+"  # Version numbers: v2.1.0
    r"|[A-Z][a-z]{0,3}\."  # Abbreviations: Dr., Inc.
    r"|\w+\.\w{2,6}(?:/|\s|$)"  # URLs: example.com
)


def split_sentences(text: str, max_chars: int = 400) -> list[str]:
    """
    Split text into sentence-level chunks suitable for streaming.
    Avoids splitting at false sentence boundaries (decimals, abbreviations, URLs).
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if len(text) <= max_chars:
        return [text]

    # First split at apparent sentence boundaries
    raw_sentences = _SENTENCE_END.split(text)
    raw_sentences = [s.strip() for s in raw_sentences if s.strip()]

    if not raw_sentences:
        return [text]

    # Merge back sentences that were split at false boundaries
    merged: list[str] = []
    i = 0
    while i < len(raw_sentences):
        current = raw_sentences[i]

        # Check if current sentence ends with a false boundary pattern
        # If so, merge with next sentence
        while i + 1 < len(raw_sentences):
            # Check if the END of current matches a false boundary
            match = None
            for m in _FALSE_ENDS.finditer(current):
                match = m  # Get last match

            # If last match is at the end of the string (within 2 chars for trailing punctuation),
            # merge with next sentence. The -2 tolerance accounts for patterns like "v2.1." where
            # the period after the false-end pattern should still trigger a merge.
            if match and match.end() >= len(current) - 2:
                current = current + " " + raw_sentences[i + 1]
                i += 1
            else:
                break

        merged.append(current)
        i += 1

    # Now apply max_chars chunking
    chunks: list[str] = []
    current = ""

    for sentence in merged:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = current + " " + sentence
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            result.append(chunk)
        else:
            result.extend(_split_at_words(chunk, max_chars))

    return [c for c in result if c.strip()]


def _split_at_words(text: str, max_chars: int) -> list[str]:
    """Split text at word boundary when it exceeds max_chars."""
    words = text.split()
    parts: list[str] = []
    current = ""

    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            parts.append(current)
            current = word

    if current:
        parts.append(current)

    return parts
