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


# === Tests for 5 missing upstream generation parameters ===


@pytest.mark.parametrize(
    "value,expected_status",
    [
        (5.0, 200),  # Default value
        (0.0, 200),  # Minimum valid
        (10.0, 200),  # High valid
        (-1.0, 422),  # Invalid: negative
    ],
)
def test_speech_layer_penalty_factor(client, value, expected_status):
    """layer_penalty_factor parameter validation."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "layer_penalty_factor": value,
        },
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize(
    "value,expected_status",
    [
        (True, 200),  # Default
        (False, 200),  # Disabled
    ],
)
def test_speech_preprocess_prompt(client, value, expected_status):
    """preprocess_prompt parameter validation."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "preprocess_prompt": value,
        },
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize(
    "value,expected_status",
    [
        (True, 200),  # Default
        (False, 200),  # Disabled
    ],
)
def test_speech_postprocess_output(client, value, expected_status):
    """postprocess_output parameter validation."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "postprocess_output": value,
        },
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize(
    "value,expected_status",
    [
        (15.0, 200),  # Default
        (5.0, 200),  # Short chunks
        (30.0, 200),  # Long chunks
        (0.0, 422),  # Invalid: zero
        (-1.0, 422),  # Invalid: negative
    ],
)
def test_speech_audio_chunk_duration(client, value, expected_status):
    """audio_chunk_duration parameter validation."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "audio_chunk_duration": value,
        },
    )
    assert resp.status_code == expected_status


@pytest.mark.parametrize(
    "value,expected_status",
    [
        (30.0, 200),  # Default
        (10.0, 200),  # Low threshold
        (60.0, 200),  # High threshold
        (0.0, 422),  # Invalid: zero
        (-1.0, 422),  # Invalid: negative
    ],
)
def test_speech_audio_chunk_threshold(client, value, expected_status):
    """audio_chunk_threshold parameter validation."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "audio_chunk_threshold": value,
        },
    )
    assert resp.status_code == expected_status


# ============================================================================
# Instruction Validation Tests (Wave 1 - Task 2)
# ============================================================================


@pytest.mark.parametrize(
    "instructions,expected_status",
    [
        # Valid canonical instructions
        ("female", 200),
        ("british accent", 200),
        ("young adult", 200),
        ("high pitch", 200),
        ("whisper", 200),
        ("female,british accent,young adult,high pitch", 200),
        ("male,middle-aged,moderate pitch,american accent", 200),
        # Short accent aliases (should be canonicalized)
        ("british", 200),
        ("american", 200),
        ("australian", 200),
        ("canadian", 200),
        ("indian", 200),
        ("chinese", 200),
        ("korean", 200),
        ("japanese", 200),
        ("portuguese", 200),
        ("russian", 200),
        # Unsupported emotion attributes (MUST FAIL)
        ("cheerful", 422),
        ("sad", 422),
        ("angry", 422),
        ("surprised", 422),
        ("happy", 422),
        ("fearful", 422),
        ("disgusted", 422),
        # Unsupported speaking style attributes (MUST FAIL)
        ("narration", 422),
        ("customer_service", 422),
        ("news_presentation", 422),
        ("sportscasting", 422),
        # Conflicting categories (MUST FAIL)
        ("male,female", 422),
        ("child,elderly", 422),
        ("very low pitch,very high pitch", 422),
        # Duplicate handling
        ("female,female", 200),  # Duplicates should be deduplicated
        ("british accent,british accent", 200),
        # Empty instructions
        ("", 422),
        ("   ", 422),
    ],
    ids=[
        "valid-female",
        "valid-british-accent",
        "valid-young-adult",
        "valid-high-pitch",
        "valid-whisper",
        "valid-combined",
        "valid-default-preset",
        "alias-british",
        "alias-american",
        "alias-australian",
        "alias-canadian",
        "alias-indian",
        "alias-chinese",
        "alias-korean",
        "alias-japanese",
        "alias-portuguese",
        "alias-russian",
        "unsupported-cheerful",
        "unsupported-sad",
        "unsupported-angry",
        "unsupported-surprised",
        "unsupported-happy",
        "unsupported-fearful",
        "unsupported-disgusted",
        "unsupported-narration",
        "unsupported-customer-service",
        "unsupported-news-presentation",
        "unsupported-sportscasting",
        "conflict-gender",
        "conflict-age",
        "conflict-pitch",
        "duplicate-gender",
        "duplicate-accent",
        "empty-string",
        "whitespace-only",
    ],
)
def test_speech_instruction_validation(client, instructions, expected_status):
    """Test instruction validation for supported/unsupported attributes."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "instructions": instructions,
            "response_format": "pcm",
        },
    )
    assert resp.status_code == expected_status

    if expected_status == 422:
        body = resp.json()
        error_msg = body.get("error", {}).get("message") or body.get("detail", "")
        assert error_msg, "422 response must include error message"


def test_speech_instruction_accent_alias_canonicalization(client):
    """Short accent aliases should be canonicalized to full form."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "instructions": "british",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    # Should be canonicalized to "british accent"
    assert "british accent" in req.instruct.lower()


def test_speech_instruction_unsupported_emotion_error_message(client):
    """Unsupported emotion attributes should return actionable error."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "instructions": "cheerful",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    error_msg = body.get("error", {}).get("message") or body.get("detail", "")
    assert "cheerful" in error_msg.lower()
    assert "not supported" in error_msg.lower() or "unsupported" in error_msg.lower()


def test_speech_instruction_conflict_error_message(client):
    """Conflicting categories should return actionable error."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello",
            "instructions": "male,female",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    error_msg = body.get("error", {}).get("message") or body.get("detail", "")
    assert "conflict" in error_msg.lower() or "multiple" in error_msg.lower()
    assert "gender" in error_msg.lower() or "male" in error_msg.lower()


def test_speech_instruction_chinese_dialect_supported(client):
    """Chinese dialect attributes should be accepted."""
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "你好",
            "instructions": "female,四川话",
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    req = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert req.mode == "design"
    assert "四川话" in req.instruct
