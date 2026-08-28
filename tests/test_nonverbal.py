"""
Tests for issue #37 — non-verbal symbols producing noise.

Two independent mitigations are covered here:
  1. Unknown bracketed tags are reported rather than silently synthesised as
     literal text.
  2. Generations that come back near-silent are re-rolled deterministically.
"""

from __future__ import annotations

import torch

from omnivoice_server.utils.audio import is_degenerate_audio, speech_window_ratio
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


# ── No-speech detection ──────────────────────────────────────────────────────
#
# Thresholds here are calibrated against real output from k2-fsa/OmniVoice,
# recorded while investigating issue #37:
#
#   plain text, no tags     speech-window ratio 0.71, 0.75, 1.00
#   one non-verbal tag                           0.38
#   three tags (the report)                      0.00  (6 samples, 4 parameter
#                                                       configurations)
#
# The synthetic signals below are shaped to land in the same places.


def _drone(duration_s: float, freq: float = 30.0, amplitude: float = 0.15) -> torch.Tensor:
    """
    Loud, steady, very low frequency — the shape of the issue #37 failure.

    Deliberately not quiet: the real failure runs at RMS 2500-12000 with only
    2.7% of frames near-silent. A detector keying on loudness misses it, which
    is exactly what the first attempt at this did.
    """
    t = torch.arange(int(SAMPLE_RATE * duration_s), dtype=torch.float32) / SAMPLE_RATE
    return (amplitude * torch.sin(2 * torch.pi * freq * t)).unsqueeze(0)


def _speech_like(duration_s: float, amplitude: float = 0.2, seed: int = 0) -> torch.Tensor:
    """
    Harmonic stack reaching into the fricative range, under a syllable-rate
    envelope. A bare 220Hz tone will not do: its zero-crossing rate is 0.018,
    below the speech threshold, so it would read as a drone.
    """
    generator = torch.Generator().manual_seed(seed)
    n = int(SAMPLE_RATE * duration_s)
    t = torch.arange(n, dtype=torch.float32) / SAMPLE_RATE

    signal = torch.zeros(n)
    for i, freq in enumerate([140, 280, 560, 1120, 2240, 3360]):
        signal += torch.sin(2 * torch.pi * freq * t) / (i + 1)
    signal *= 0.6 + 0.4 * torch.sin(2 * torch.pi * 4 * t)
    signal += 0.35 * torch.randn(n, generator=generator)

    return (amplitude * signal / signal.abs().max()).unsqueeze(0)


def _whisper_like(duration_s: float, seed: int = 1) -> torch.Tensor:
    """Quiet broadband noise — a whispered render, which must not be flagged."""
    generator = torch.Generator().manual_seed(seed)
    return (0.02 * torch.randn(int(SAMPLE_RATE * duration_s), generator=generator)).unsqueeze(0)


def test_speech_scores_high():
    assert speech_window_ratio([_speech_like(3.0)]) > 0.9


def test_drone_scores_zero():
    assert speech_window_ratio([_drone(3.8)]) == 0.0


def test_drone_is_flagged():
    assert is_degenerate_audio([_drone(3.8)], min_speech_ratio=0.15)


def test_speech_is_not_flagged():
    assert not is_degenerate_audio([_speech_like(3.0)], min_speech_ratio=0.15)


def test_loud_drone_is_flagged_despite_being_loud():
    """
    The regression this whole change exists for. The first detector looked for
    near-silence; the real failure is loud and steady, so it never fired.
    """
    loud = _drone(3.8, amplitude=0.4)
    assert loud.abs().max() > 0.3
    assert is_degenerate_audio([loud], min_speech_ratio=0.15)


def test_whisper_is_not_flagged():
    """Whispering is quiet but broadband, so its ZCR is high, not low."""
    assert not is_degenerate_audio([_whisper_like(4.0)], min_speech_ratio=0.15)


def test_pauses_do_not_count_against_speech():
    """Silence between sentences is excluded rather than scored as failure."""
    speech = _speech_like(1.5)
    silence = torch.zeros(1, int(SAMPLE_RATE * 2.0))
    assert not is_degenerate_audio([speech, silence, speech], min_speech_ratio=0.15)


def test_short_output_is_never_flagged():
    """Too few windows to judge, and onset/decay dominate."""
    assert not is_degenerate_audio([_drone(0.4)], min_speech_ratio=0.15)


def test_empty_output_is_not_flagged():
    assert not is_degenerate_audio([], min_speech_ratio=0.15)


def test_silent_output_is_not_flagged_as_a_drone():
    """
    All-silence is a different failure and not what this detects; scoring it
    here would report the wrong cause.
    """
    assert not is_degenerate_audio([torch.zeros(1, SAMPLE_RATE * 3)], min_speech_ratio=0.15)


def test_sub_frame_input_does_not_divide_by_zero():
    assert speech_window_ratio([torch.zeros(1, 10)]) == 1.0


def test_nan_samples_do_not_poison_the_score():
    signal = torch.full((1, SAMPLE_RATE * 3), float("nan"))
    assert speech_window_ratio([signal]) == 1.0


def test_multiple_tensors_are_scored_as_one_stream():
    assert is_degenerate_audio([_drone(2.0), _drone(2.0)], min_speech_ratio=0.15)


# ── Streaming responses ──────────────────────────────────────────────────────


def test_streamed_response_reports_unknown_tags(client):
    """
    A retry cannot be reported on a stream — headers go out first — but a typo
    is knowable before generation starts, and streaming callers make typos too.
    """
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hi [laugh] there", "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Unknown-Nonverbal-Tags"] == "laugh"


def test_streamed_response_omits_the_header_when_tags_are_valid(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hi [laughter] there", "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    assert "X-Unknown-Nonverbal-Tags" not in resp.headers


def test_streamed_response_keeps_its_pcm_headers(client):
    """The new header must not displace the format headers clients rely on."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hi [laugh] there", "stream": True, "response_format": "pcm"},
    )
    assert resp.headers["X-Audio-Sample-Rate"] == "24000"
    assert resp.headers["X-Audio-Format"] == "pcm-int16-le"
