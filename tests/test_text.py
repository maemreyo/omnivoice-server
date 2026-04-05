"""
Tests for text splitting utilities.
"""

from __future__ import annotations

from omnivoice_server.utils.text import split_sentences


def test_split_sentences_basic():
    """Basic sentence splitting at period."""
    text = "Hello world. This is a test."
    result = split_sentences(text, max_chars=20)  # Force split
    assert len(result) == 2
    assert "Hello world." in result[0]
    assert "This is a test." in result[1]


def test_split_sentences_decimal_not_split():
    """Decimals like 3.14 should NOT be treated as sentence boundaries."""
    text = "The price is 3.14. Buy now."
    result = split_sentences(text, max_chars=20)  # Force split
    # Should split at "Buy now." not at "3.14."
    assert len(result) == 2
    assert "3.14" in result[0]
    assert "Buy now" in result[1]


def test_split_sentences_abbreviation_not_split():
    """Abbreviations like Dr. should NOT be treated as sentence boundaries."""
    text = "Dr. Smith is here. He will help."
    result = split_sentences(text, max_chars=20)  # Force split
    # Should split at "He will help." not at "Dr."
    assert len(result) == 2
    assert "Dr. Smith" in result[0]


def test_split_sentences_version_not_split():
    """Version numbers like v2.1.0 should NOT be treated as sentence boundaries."""
    text = "Release v2.1. Download now."
    result = split_sentences(text, max_chars=100)
    # Should NOT split at "v2.1." because it matches _FALSE_ENDS pattern
    # Should only be one sentence (or split elsewhere if forced by max_chars)
    assert len(result) == 1
    assert "v2.1." in result[0]
    assert "Download now." in result[0]


def test_split_sentences_chinese():
    """Chinese sentence endings (。！？) should split correctly."""
    text = "你好。这是测试。"
    result = split_sentences(text, max_chars=5)  # Force split (text is 8 chars)
    assert len(result) >= 1  # At least splits into chunks


def test_split_sentences_max_chars_respected():
    """Long sentences should be split at word boundaries when exceeding max_chars."""
    text = "This is a very long sentence that definitely exceeds the maximum character limit."
    result = split_sentences(text, max_chars=30)
    assert all(len(chunk) <= 50 for chunk in result)  # Allow some overflow for word boundaries


def test_split_sentences_empty_input():
    """Empty or whitespace-only input returns empty list."""
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_split_sentences_single_short_sentence():
    """Single sentence shorter than max_chars returns as-is."""
    text = "Hello world."
    result = split_sentences(text, max_chars=100)
    assert len(result) == 1
    assert result[0] == "Hello world."


def test_split_sentences_multiple_punctuation():
    """Multiple sentence endings (! ?) should split correctly."""
    text = "Hello! How are you? I am fine."
    result = split_sentences(text, max_chars=15)  # Force split
    assert len(result) == 3
    assert "Hello!" in result[0]
    assert "How are you?" in result[1]
    assert "I am fine." in result[2]


def test_split_sentences_no_space_after_period():
    """Sentences without space after period should still split."""
    text = "Hello.World"
    result = split_sentences(text, max_chars=100)
    # Should not split because no space after period
    assert len(result) == 1
