"""
Tests for streaming synthesis endpoint.

The streaming test was previously buried in test_voices.py — moved here where
it belongs, with additional edge-case coverage.
"""

from __future__ import annotations


def test_streaming_returns_pcm_headers(client):
    """Streaming response must set the PCM metadata headers."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello world. This is sentence two.",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Audio-Sample-Rate") == "24000"
    assert resp.headers.get("X-Audio-Channels") == "1"
    assert resp.headers.get("X-Audio-Bit-Depth") == "16"
    assert resp.headers.get("X-Audio-Format") == "pcm-int16-le"


def test_streaming_content_type_is_pcm(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]


def test_streaming_returns_bytes(client):
    """Should yield at least some PCM bytes for non-empty input."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello world.", "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_streaming_multi_sentence(client):
    """Multiple sentences should all be synthesized.

    Note: split_sentences merges short sentences into chunks (max 400 chars by default).
    The 3 short sentences below get merged into 1 chunk, so we expect 1 synthesis call
    returning 48KB (1s × 24kHz × 2 bytes), not 3 separate calls.
    """
    text = "First sentence. Second sentence. Third sentence."
    resp = client.post(
        "/v1/audio/speech",
        json={"input": text, "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    # Short sentences get merged into 1 chunk → 1s silence = 48000 samples × 2 bytes
    assert len(resp.content) >= 48000


def test_streaming_clone_prefix_nonexistent_profile_returns_404(client):
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello.",
            "voice": "clone:stream-test",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 404


def test_streaming_empty_text_rejected(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "", "stream": True},
    )
    assert resp.status_code == 422


def test_streaming_bare_unknown_voice_falls_back_to_design(client):
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello.",
            "voice": "unknownvoicename",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200


def test_streaming_does_not_return_wav_header(client):
    """
    PCM stream must NOT start with RIFF — that would be a WAV header embedded
    in a raw PCM stream, which would corrupt the audio.
    """
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True, "response_format": "pcm"},
    )
    assert resp.status_code == 200
    if len(resp.content) >= 4:
        assert resp.content[:4] != b"RIFF", (
            "Streaming returned WAV header in PCM stream — "
            "check that streaming uses tensor_to_pcm16_bytes, not tensors_to_wav_bytes"
        )
