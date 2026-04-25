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


def test_streaming_bare_unknown_voice_returns_422(client):
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello.",
            "voice": "unknownvoicename",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 422
    assert "Unsupported voice value" in resp.text


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


def test_force_streaming_cfg_overrides_request(client, monkeypatch):
    """When cfg.stream=True, request without stream=True should still stream."""
    monkeypatch.setattr(client.app.state.cfg, "stream", True)
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello world.", "response_format": "pcm"},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]
    assert resp.headers.get("X-Audio-Sample-Rate") == "24000"


def test_force_streaming_cfg_rejects_non_pcm(client, monkeypatch):
    """When cfg.stream=True, non-PCM response_format should return 400."""
    monkeypatch.setattr(client.app.state.cfg, "stream", True)
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "response_format": "wav"},
    )
    assert resp.status_code == 400
    error_msg = resp.json().get("detail") or resp.json().get("error", {}).get("message", "")
    assert "response_format='pcm'" in error_msg


def test_streaming_overlap_default_off_uses_sequential_path(client, monkeypatch):
    from omnivoice_server.routers import speech

    calls = {"sequential": 0, "overlapped": 0}

    async def sequential(*_args, **_kwargs):
        calls["sequential"] += 1
        yield b"pcm"

    async def overlapped(*_args, **_kwargs):
        calls["overlapped"] += 1
        yield b"pcm"

    monkeypatch.setattr(speech, "_stream_sentences", sequential)
    monkeypatch.setattr(speech, "_stream_sentences_overlapped", overlapped)
    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", False)

    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True, "response_format": "pcm"},
    )

    assert resp.status_code == 200
    assert calls["sequential"] == 1
    assert calls["overlapped"] == 0


def test_streaming_overlap_opt_in_uses_overlapped_path(client, monkeypatch):
    from omnivoice_server.routers import speech

    calls = {"sequential": 0, "overlapped": 0}

    async def sequential(*_args, **_kwargs):
        calls["sequential"] += 1
        yield b"pcm"

    async def overlapped(*_args, **_kwargs):
        calls["overlapped"] += 1
        yield b"pcm"

    monkeypatch.setattr(speech, "_stream_sentences", sequential)
    monkeypatch.setattr(speech, "_stream_sentences_overlapped", overlapped)
    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", True)

    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True, "response_format": "pcm"},
    )

    assert resp.status_code == 200
    assert calls["overlapped"] == 1
    assert calls["sequential"] == 0


def test_streaming_overlap_returns_bytes_for_multiple_chunks(client, monkeypatch):
    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", True)
    monkeypatch.setattr(client.app.state.cfg, "stream_chunk_max_chars", 20)
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "First sentence is long enough. Second sentence is long enough.",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert len(resp.content) >= 96000


def test_streaming_overlap_error_mid_stream_delivers_partial(client, monkeypatch):
    """Error on 2nd synthesize call: first chunk is delivered and stream ends cleanly."""
    from unittest.mock import AsyncMock

    import torch

    from omnivoice_server.services.inference import SynthesisResult

    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", True)
    monkeypatch.setattr(client.app.state.cfg, "stream_chunk_max_chars", 20)

    call_count = [0]

    async def synthesize_fail_second(req, **_kwargs):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise RuntimeError("Model error on chunk 2")
        tensor = torch.zeros(1, 24_000)
        return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)

    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=synthesize_fail_second)

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "First sentence long enough. Second sentence also.",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert 0 < len(resp.content) < 96000  # partial: only first chunk delivered


def test_streaming_overlap_timeout_mid_stream_delivers_partial(client, monkeypatch):
    """Timeout on 2nd synthesize call: first chunk is delivered and stream ends cleanly."""
    import asyncio
    from unittest.mock import AsyncMock

    import torch

    from omnivoice_server.services.inference import SynthesisResult

    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", True)
    monkeypatch.setattr(client.app.state.cfg, "stream_chunk_max_chars", 20)

    call_count = [0]

    async def synthesize_timeout_second(req, **_kwargs):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise asyncio.TimeoutError()
        tensor = torch.zeros(1, 24_000)
        return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)

    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=synthesize_timeout_second)

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "First sentence long enough. Second sentence also.",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert 0 < len(resp.content) < 96000


def test_streaming_overlap_outer_guard_no_hang(client, monkeypatch):
    """Unexpected error outside inner try puts sentinel so consumer never hangs."""
    from omnivoice_server.routers import speech

    monkeypatch.setattr(client.app.state.cfg, "stream_overlap", True)
    monkeypatch.setattr(client.app.state.cfg, "stream_chunk_max_chars", 20)

    original = speech._chunk_request
    call_count = [0]

    def fail_on_second(sentence, base_req):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("Unexpected error outside inner try-except")
        return original(sentence, base_req)

    monkeypatch.setattr(speech, "_chunk_request", fail_on_second)

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "First sentence long. Second sentence also.",
            "stream": True,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert len(resp.content) > 0  # first chunk delivered before outer guard fired
