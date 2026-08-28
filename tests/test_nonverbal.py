"""
Tests for issue #37 — non-verbal symbols producing noise.

Two independent mitigations are covered here:
  1. Unknown bracketed tags are reported rather than silently synthesised as
     literal text.
  2. Generations that come back near-silent are re-rolled deterministically.
"""

from __future__ import annotations

import torch

from omnivoice_server.utils.audio import is_degenerate_audio, silent_frame_fraction
from omnivoice_server.utils.text import (
    NONVERBAL_TAGS,
    count_nonverbal_tags,
    find_nonverbal_tags,
    find_unknown_nonverbal_tags,
)

SAMPLE_RATE = 24_000


def _speech_like(duration_s: float, amplitude: float = 0.2) -> torch.Tensor:
    """Continuous non-silent audio — stands in for a healthy generation."""
    n = int(SAMPLE_RATE * duration_s)
    t = torch.arange(n, dtype=torch.float32) / SAMPLE_RATE
    return (amplitude * torch.sin(2 * torch.pi * 220 * t)).unsqueeze(0)


def _mostly_silent(duration_s: float, burst_s: float = 0.3) -> torch.Tensor:
    """
    Near-silence with one loud burst — the shape of the failure in issue #37,
    where per-second RMS was ~100-250 for 6.5s with a single burst at the end.
    """
    n = int(SAMPLE_RATE * duration_s)
    out = torch.full((n,), 1e-4, dtype=torch.float32)
    burst = int(SAMPLE_RATE * burst_s)
    out[-burst:] = 0.3
    return out.unsqueeze(0)


# ── Tag parsing ──────────────────────────────────────────────────────────────


def test_reporter_input_parses_as_three_known_tags():
    """The exact text from issue #37 uses only supported tags."""
    text = "Hello [laughter] this is amazing [breath] really cool [sigh]"
    assert find_nonverbal_tags(text) == ["laughter", "breath", "sigh"]
    assert count_nonverbal_tags(text) == 3
    assert find_unknown_nonverbal_tags(text) == []


def test_unknown_tags_are_reported():
    assert find_unknown_nonverbal_tags("hi [laugh] there") == ["laugh"]


def test_unknown_tags_are_deduplicated_in_order():
    text = "[laugh] a [cough] b [laugh] c [breath]"
    assert find_unknown_nonverbal_tags(text) == ["laugh", "cough"]


def test_tag_matching_is_case_insensitive():
    assert find_unknown_nonverbal_tags("[Laughter] and [SIGH]") == []


def test_text_without_tags_yields_nothing():
    assert find_nonverbal_tags("Plain text, no brackets.") == []
    assert find_unknown_nonverbal_tags("") == []


def test_every_documented_tag_is_recognised():
    """Guards against the docs and the code drifting apart."""
    documented = {
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
    assert NONVERBAL_TAGS == documented


# ── Degenerate output detection ──────────────────────────────────────────────


def test_healthy_audio_has_no_silent_frames():
    assert silent_frame_fraction([_speech_like(3.0)], silence_rms=0.01) == 0.0


def test_failure_shaped_audio_is_mostly_silent():
    fraction = silent_frame_fraction([_mostly_silent(7.0)], silence_rms=0.01)
    assert fraction > 0.9


def test_healthy_audio_is_not_flagged():
    assert not is_degenerate_audio(
        [_speech_like(3.0)], silence_rms=0.01, max_silent_fraction=0.75
    )


def test_failure_shaped_audio_is_flagged():
    assert is_degenerate_audio(
        [_mostly_silent(7.0)], silence_rms=0.01, max_silent_fraction=0.75
    )


def test_quiet_but_continuous_audio_is_not_flagged():
    """
    A whispered render is quiet everywhere but silent nowhere. Overall RMS would
    condemn it; frame distribution correctly clears it.
    """
    whisper = _speech_like(4.0, amplitude=0.03)
    assert not is_degenerate_audio(
        [whisper], silence_rms=0.01, max_silent_fraction=0.75
    )


def test_short_output_is_never_flagged():
    """A one-word render is legitimately mostly silence; re-rolling wastes time."""
    assert not is_degenerate_audio(
        [_mostly_silent(0.4)], silence_rms=0.01, max_silent_fraction=0.75
    )


def test_empty_output_is_not_flagged():
    assert not is_degenerate_audio([], silence_rms=0.01, max_silent_fraction=0.75)
    assert silent_frame_fraction([], silence_rms=0.01) == 0.0


def test_sub_frame_input_does_not_divide_by_zero():
    tiny = torch.zeros(1, 10)
    assert silent_frame_fraction([tiny], silence_rms=0.01) == 0.0


def test_nan_samples_count_as_silence_rather_than_poisoning_the_mean():
    """NaN would otherwise make every frame RMS NaN, and NaN < x is False."""
    n = int(SAMPLE_RATE * 3)
    signal = torch.full((1, n), float("nan"))
    assert silent_frame_fraction([signal], silence_rms=0.01) == 1.0


def test_multiple_tensors_are_scored_as_one_stream():
    chunks = [_mostly_silent(3.0), _mostly_silent(3.0)]
    assert is_degenerate_audio(chunks, silence_rms=0.01, max_silent_fraction=0.75)
