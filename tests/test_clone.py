"""
Tests for one-shot voice cloning endpoint.
"""

from __future__ import annotations

import io
import os
from unittest.mock import AsyncMock

import torch

from omnivoice_server.services.inference import SynthesisResult


def test_clone_returns_wav(client, sample_audio_bytes):
    """POST /v1/audio/speech/clone returns WAV."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "speed": "1.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"


def test_clone_response_format_pcm(client, sample_audio_bytes):
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "response_format": "pcm"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]
    assert resp.content[:4] != b"RIFF"


def test_clone_streaming_returns_pcm_headers(client, sample_audio_bytes):
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "stream": "true", "response_format": "pcm"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]
    assert resp.headers.get("X-Audio-Sample-Rate") == "24000"
    assert resp.headers.get("X-Audio-Channels") == "1"
    assert resp.headers.get("X-Audio-Bit-Depth") == "16"
    assert resp.headers.get("X-Audio-Format") == "pcm-int16-le"
    assert len(resp.content) > 0
    assert resp.content[:4] != b"RIFF"


def test_clone_streaming_rejects_non_pcm(client, sample_audio_bytes):
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "stream": "true", "response_format": "wav"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 400
    error_msg = resp.json().get("detail") or resp.json().get("error", {}).get("message", "")
    assert "response_format='pcm'" in error_msg


def test_clone_streaming_keeps_ref_audio_available(client, sample_audio_bytes):
    seen_paths = []

    async def synthesize(req, **_kwargs):
        seen_paths.append(req.ref_audio_path)
        assert req.mode == "clone"
        assert req.ref_audio_path is not None
        assert os.path.exists(req.ref_audio_path)
        tensor = torch.zeros(1, 24_000)
        return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)

    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=synthesize)
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "stream": "true", "response_format": "pcm"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert seen_paths
    assert not os.path.exists(seen_paths[0])


def test_clone_force_streaming_cfg_rejects_default_wav(client, sample_audio_bytes, monkeypatch):
    monkeypatch.setattr(client.app.state.cfg, "stream", True)
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 400
    error_msg = resp.json().get("detail") or resp.json().get("error", {}).get("message", "")
    assert "response_format='pcm'" in error_msg


def test_clone_force_streaming_cfg_accepts_pcm(client, sample_audio_bytes, monkeypatch):
    monkeypatch.setattr(client.app.state.cfg, "stream", True)
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "response_format": "pcm"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]
    assert resp.headers.get("X-Audio-Sample-Rate") == "24000"


def test_clone_empty_audio_rejected(client):
    """Empty audio returns 422."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello"},
        files={"ref_audio": ("ref.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert resp.status_code == 422


# === Tests for 5 missing upstream generation parameters (clone endpoint) ===


def test_clone_layer_penalty_factor_valid(client, sample_audio_bytes):
    """Clone endpoint accepts layer_penalty_factor parameter."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "layer_penalty_factor": "5.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_layer_penalty_factor_invalid(client, sample_audio_bytes):
    """Clone endpoint rejects negative layer_penalty_factor."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "layer_penalty_factor": "-1.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 422


def test_clone_preprocess_prompt_true(client, sample_audio_bytes):
    """Clone endpoint accepts preprocess_prompt=true."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "preprocess_prompt": "true"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_preprocess_prompt_false(client, sample_audio_bytes):
    """Clone endpoint accepts preprocess_prompt=false."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "preprocess_prompt": "false"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_postprocess_output_true(client, sample_audio_bytes):
    """Clone endpoint accepts postprocess_output=true."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "postprocess_output": "true"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_postprocess_output_false(client, sample_audio_bytes):
    """Clone endpoint accepts postprocess_output=false."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "postprocess_output": "false"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_audio_chunk_duration_valid(client, sample_audio_bytes):
    """Clone endpoint accepts audio_chunk_duration parameter."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "audio_chunk_duration": "15.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_audio_chunk_duration_invalid(client, sample_audio_bytes):
    """Clone endpoint rejects zero audio_chunk_duration."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "audio_chunk_duration": "0.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 422


def test_clone_audio_chunk_threshold_valid(client, sample_audio_bytes):
    """Clone endpoint accepts audio_chunk_threshold parameter."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "audio_chunk_threshold": "30.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200


def test_clone_audio_chunk_threshold_invalid(client, sample_audio_bytes):
    """Clone endpoint rejects negative audio_chunk_threshold."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "audio_chunk_threshold": "-1.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 422
