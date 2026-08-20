"""
Sentence splitting for streaming mode.

Goal: Split text into chunks that:
  1. End at natural sentence boundaries (. ! ? newline)
  2. Don't exceed max_chars
  3. Don't split in the middle of numbers, abbreviations, URLs
"""

from __future__ import annotations

import re

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


def split_sentences(
    text: str,
    max_chars: int = 400,
    eager_first_chunk: bool = False,
    min_chunk_chars: int = 0,
) -> list[str]:
    """
    Split text into sentence-level chunks suitable for streaming.
    Avoids splitting at false sentence boundaries (decimals, abbreviations, URLs).
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    max_chars = max(max_chars, 1)
    min_chunk_chars = min(max(min_chunk_chars, 0), max_chars)

    if len(text) <= max_chars and not eager_first_chunk:
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

    # Streaming TTFA optimization: emit the first natural sentence as soon as
    # possible, then fall back to merged chunking for the rest of the text.
    if eager_first_chunk and merged:
        first_sentence = merged[0]
        if len(first_sentence) <= max_chars:
            first_chunks = [first_sentence]
            remaining_sentences = merged[1:]
        else:
            split_first = _split_at_words(first_sentence, max_chars)
            first_chunks = split_first[:1]
            remaining_sentences = split_first[1:] + merged[1:]

        result = first_chunks + _chunk_sentences(
            remaining_sentences, max_chars, min_chunk_chars
        )
        return [c for c in result if c.strip()]

    return [
        c for c in _chunk_sentences(merged, max_chars, min_chunk_chars) if c.strip()
    ]


def _chunk_sentences(
    sentences: list[str], max_chars: int, min_chunk_chars: int = 0
) -> list[str]:
    """Merge short adjacent sentences, bounded by ``max_chars``."""
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
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

    if min_chunk_chars <= 0:
        return result

    # A short trailing chunk can occur after a punctuation/word boundary.
    # Merge it backward when the maximum-size constraint permits it. This is
    # deliberately best-effort: max_chars always wins over the minimum.
    merged_result: list[str] = []
    for chunk in result:
        if (
            merged_result
            and len(chunk) < min_chunk_chars
            and len(merged_result[-1]) + 1 + len(chunk) <= max_chars
        ):
            merged_result[-1] += " " + chunk
        else:
            merged_result.append(chunk)
    return merged_result


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
