"""
Tests for one-shot voice cloning endpoint.
"""

from __future__ import annotations

import io


def test_clone_returns_wav(client, sample_audio_bytes):
    """POST /v1/audio/speech/clone returns WAV."""
    resp = client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello world", "speed": "1.0"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"


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
