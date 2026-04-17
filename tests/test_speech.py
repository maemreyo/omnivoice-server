"""
Tests for speech synthesis endpoints.
"""

from __future__ import annotations

import shutil

import pytest


def test_speech_default_returns_wav(client):
    """Default response_format returns WAV (no pydub required)."""
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
    """voice field should be ignored for /v1/audio/speech."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "design:female,british accent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, moderate pitch, british accent"


def test_speech_auto_uses_default_design_prompt(client):
    """auto should resolve to the server's default design prompt."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "auto",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, moderate pitch, british accent"


def test_speech_openai_voice_preset_maps_to_design_prompt(client):
    """Recognized voice names should map to local design presets."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "alloy",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "female, young adult, moderate pitch, american accent"


def test_speech_speaker_field_maps_to_design_prompt(client):
    """speaker should work as an alias for preset selection."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "speaker": "onyx",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, very low pitch, british accent"


def test_speech_default_voice_uses_default_design_prompt(client):
    """Omitting voice should use the same default design prompt."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, moderate pitch, british accent"


def test_speech_design_instructions_field(client):
    """Explicit instructions should drive design mode."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "auto",
            "instructions": "female,british accent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "female,british accent"


def test_speech_instructions_override_voice_design_shorthand(client):
    """instructions should take precedence over voice design shorthand."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "design:male,deep voice",
            "instructions": "female,british accent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "female,british accent"


def test_speech_ignores_clone_voice_when_instructions_missing(client):
    """clone:* in the voice field should be ignored by /v1/audio/speech."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "clone:nonexistent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, moderate pitch, british accent"


def test_speech_ignores_voice_when_instructions_present(client):
    """instructions should be used even if voice contains an OpenAI voice name."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "alloy",
            "instructions": "female,british accent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "female,british accent"


def test_speech_speaker_takes_precedence_over_voice_preset(client):
    """speaker should win when both preset selectors are provided."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "alloy",
            "speaker": "cedar",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, low pitch, american accent"


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


def test_speech_clone_unknown_profile_ignored(client):
    """clone:* values are ignored by /v1/audio/speech unless cloning endpoint is used."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "voice": "clone:nonexistent",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert req.instruct == "male, middle-aged, moderate pitch, british accent"


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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not found on PATH")
def test_speech_mp3_format(client):
    """response_format=mp3 returns audio/mpeg."""
    pydub = pytest.importorskip("pydub")
    del pydub  # silence lint; we just need to verify it's importable

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "mp3",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    # MP3 files start with ID3 or MPEG sync word (0xFFE0 masks the 3-bit layer/version)
    assert resp.content[:3] == b"ID3" or (
        resp.content[0] == 0xFF and resp.content[1] & 0xE0 == 0xE0
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not found on PATH")
def test_speech_opus_format(client):
    """response_format=opus returns audio/ogg (Ogg container)."""
    pydub = pytest.importorskip("pydub")
    del pydub

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "opus",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/ogg"
    # Ogg files start with "OggS" magic bytes
    assert resp.content[:4] == b"OggS"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not found on PATH")
def test_speech_flac_format(client):
    """response_format=flac returns audio/flac."""
    pydub = pytest.importorskip("pydub")
    del pydub

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "flac",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/flac"
    # FLAC files start with "fLaC"
    assert resp.content[:4] == b"fLaC"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not found on PATH")
def test_speech_aac_format(client):
    """response_format=aac returns audio/aac."""
    pydub = pytest.importorskip("pydub")
    del pydub

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "aac",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/aac"
    # AAC in ADTS container starts with sync word 0xFF 0xF1 or 0xFF 0xF9
    assert resp.content[:2] == b"\xff\xf1" or resp.content[:2] == b"\xff\xf9"


def test_speech_format_not_implemented_returns_501(client, monkeypatch):
    """When pydub/ffmpeg missing, format conversion returns 501."""
    monkeypatch.setattr("omnivoice_server.utils.audio.PYDUB_AVAILABLE", False)

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "mp3",
        },
    )
    assert resp.status_code == 501
    body = resp.json()
    error_msg = body.get("detail") or body.get("error", {}).get("message", "")
    assert "mp3" in error_msg


def test_speech_format_ffmpeg_missing_returns_501(client, monkeypatch):
    """When pydub present but ffmpeg missing, format conversion returns 501."""
    monkeypatch.setattr("omnivoice_server.utils.audio.PYDUB_AVAILABLE", True)
    monkeypatch.setattr("omnivoice_server.utils.audio.FFMPEG_AVAILABLE", False)

    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "mp3",
        },
    )
    assert resp.status_code == 501
    body = resp.json()
    error_msg = body.get("detail") or body.get("error", {}).get("message", "")
    assert "ffmpeg" in error_msg.lower()


def test_speech_streaming_only_pcm(client):
    """Streaming only supports pcm format (WAV requires non-streamable RIFF headers)."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "response_format": "mp3",
            "stream": True,
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    error_msg = body.get("detail") or body.get("error", {}).get("message", "")
    assert "response_format='pcm'" in error_msg


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
