"""
Tests for OmniVoiceAdapter.build_kwargs() — the single seam against upstream
omnivoice. These run without a model: the adapter is pure kwargs construction.
"""

from __future__ import annotations

import pytest

from omnivoice_server.config import Settings
from omnivoice_server.services.inference import OmniVoiceAdapter, SynthesisRequest


@pytest.fixture
def adapter():
    return OmniVoiceAdapter(Settings(device="cpu"))


def _req(**overrides) -> SynthesisRequest:
    base = {"text": "hello", "mode": "design", "instruct": "female, british accent"}
    base.update(overrides)
    return SynthesisRequest(**base)


# ── 0.2.x parameters ─────────────────────────────────────────────────────────


def test_pad_and_fade_duration_always_sent(adapter):
    """pad_duration/fade_duration gate the tail-clipping workaround, so they
    must be present on every call, not only when explicitly overridden."""
    kwargs = adapter.build_kwargs(_req(), model=None)

    assert kwargs["pad_duration"] == 0.1
    assert kwargs["fade_duration"] == 0.1


def test_request_overrides_beat_server_defaults(adapter):
    kwargs = adapter.build_kwargs(
        _req(pad_duration=0.35, fade_duration=0.0, normalize_text=True), model=None
    )

    assert kwargs["pad_duration"] == 0.35
    assert kwargs["fade_duration"] == 0.0
    assert kwargs["normalize_text"] is True


def test_zero_override_is_not_treated_as_unset(adapter):
    """0.0 is falsy but meaningful (disables padding) — it must survive."""
    kwargs = adapter.build_kwargs(_req(pad_duration=0.0), model=None)

    assert kwargs["pad_duration"] == 0.0


def test_normalize_text_defaults_off(adapter):
    """Upstream text normalization needs the `omnivoice[tn]` extra, so the
    server must not enable it implicitly."""
    kwargs = adapter.build_kwargs(_req(), model=None)

    assert kwargs["normalize_text"] is False


def test_server_default_pad_duration_is_honoured():
    adapter = OmniVoiceAdapter(Settings(device="cpu", pad_duration=0.3))
    kwargs = adapter.build_kwargs(_req(), model=None)

    assert kwargs["pad_duration"] == 0.3


# ── Mode handling ────────────────────────────────────────────────────────────


def test_design_mode_sends_instruct_not_ref_audio(adapter):
    kwargs = adapter.build_kwargs(_req(), model=None)

    assert kwargs["instruct"] == "female, british accent"
    assert "ref_audio" not in kwargs


def test_clone_mode_sends_ref_audio(adapter):
    kwargs = adapter.build_kwargs(
        _req(mode="clone", instruct=None, ref_audio_path="/tmp/ref.wav", ref_text="hi"),
        model=None,
    )

    assert kwargs["ref_audio"] == "/tmp/ref.wav"
    assert kwargs["ref_text"] == "hi"
    assert "instruct" not in kwargs


def test_language_uses_upstream_parameter_name(adapter):
    """Upstream generate() takes `language`, not `language_id`."""
    kwargs = adapter.build_kwargs(_req(language="vi"), model=None)

    assert kwargs["language"] == "vi"
    assert "language_id" not in kwargs


def test_optional_params_omitted_when_unset(adapter):
    """None means 'let upstream decide' — the key must not be sent at all."""
    kwargs = adapter.build_kwargs(_req(), model=None)

    for key in ("duration", "language", "layer_penalty_factor", "audio_chunk_duration"):
        assert key not in kwargs
