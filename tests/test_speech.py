"""
Tests for speech synthesis endpoints.
"""

from __future__ import annotations


def test_speech_auto_returns_wav(client):
    """Auto voice mode returns WAV with RIFF header."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "model": "omnivoice",
            "input": "Hello world",
            "voice": "auto",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


def test_speech_design_voice(client):
    """Design voice with attributes."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "design:female,british accent",
        },
    )
    assert resp.status_code == 200


def test_speech_invalid_text_empty(client):
    """Empty text returns 422."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "",
            "voice": "auto",
        },
    )
    assert resp.status_code == 422


def test_speech_clone_unknown_profile(client):
    """Unknown profile returns 404."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "clone:nonexistent",
        },
    )
    assert resp.status_code == 404


def test_speech_openai_model_names_accepted(client):
    """tts-1 and tts-1-hd should be accepted for drop-in compatibility."""
    for model_name in ("tts-1", "tts-1-hd", "omnivoice"):
        resp = client.post(
            "/v1/audio/speech",
            json={
                "model": model_name,
                "input": "Hello",
            },
        )
        assert resp.status_code == 200, f"Failed for model={model_name}"


def test_speech_pcm_format(client):
    """response_format=pcm returns audio/pcm."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]


def test_speech_custom_guidance_scale(client):
    """Custom guidance_scale parameter should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "guidance_scale": 3.0,
        },
    )
    assert resp.status_code == 200


def test_speech_custom_denoise(client):
    """Custom denoise parameter should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "denoise": False,
        },
    )
    assert resp.status_code == 200


def test_speech_custom_t_shift(client):
    """Custom t_shift parameter should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "t_shift": 0.2,
        },
    )
    assert resp.status_code == 200


def test_speech_clone_invalid_audio_format(client, tmp_path):
    """Clone endpoint should reject non-audio files with 422."""
    # Create a text file pretending to be audio
    invalid_file = tmp_path / "fake.wav"
    invalid_file.write_text("This is not audio data")

    with open(invalid_file, "rb") as f:
        resp = client.post(
            "/v1/audio/speech/clone",
            data={
                "text": "Hello world",
                "speed": 1.0,
            },
            files={"ref_audio": ("fake.wav", f, "audio/wav")},
        )

    assert resp.status_code == 422
    body = resp.json()
    # Error response uses structured format: {"error": {"code": ..., "message": ...}}
    error_msg = body.get("error", {}).get("message") or body.get("detail", "")
    assert "could not parse as audio file" in error_msg


def test_speech_custom_position_temperature(client):
    """Custom position_temperature parameter should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "position_temperature": 0.0,  # Deterministic mode
        },
    )
    assert resp.status_code == 200


def test_speech_custom_class_temperature(client):
    """Custom class_temperature parameter should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "class_temperature": 0.5,
        },
    )
    assert resp.status_code == 200


