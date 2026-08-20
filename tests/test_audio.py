"""
Tests for audio utilities.
"""

from __future__ import annotations

import io

import pytest
import soundfile as sf
import torch

from omnivoice_server.utils.audio import (
    read_upload_bounded,
    tensor_to_pcm16_bytes,
    tensor_to_wav_bytes,
    tensors_to_wav_bytes,
    validate_audio_bytes,
)


def test_tensor_to_wav_bytes():
    """Convert tensor to WAV bytes with RIFF header."""
    tensor = torch.randn(1, 24000)  # 1 second at 24kHz
    wav_bytes = tensor_to_wav_bytes(tensor)

    # Check WAV magic bytes
    assert wav_bytes[:4] == b"RIFF"
    assert b"WAVE" in wav_bytes[:12]

    # Verify it's parseable
    buf = io.BytesIO(wav_bytes)
    data, sample_rate = sf.read(buf, dtype="float32")
    assert sample_rate == 24000
    assert data.ndim == 1


def test_tensors_to_wav_bytes_single():
    """Single tensor should work the same as tensor_to_wav_bytes."""
    tensor = torch.randn(1, 24000)
    result = tensors_to_wav_bytes([tensor])
    expected = tensor_to_wav_bytes(tensor)
    assert result == expected


def test_tensors_to_wav_bytes_multiple():
    """Multiple tensors should be concatenated."""
    t1 = torch.randn(1, 12000)
    t2 = torch.randn(1, 12000)
    wav_bytes = tensors_to_wav_bytes([t1, t2])

    buf = io.BytesIO(wav_bytes)
    data, _ = sf.read(buf, dtype="float32")
    assert data.shape[0] == 24000  # 12000 + 12000


def test_tensor_to_wav_bytes_stereo():
    tensor = torch.randn(2, 12000)  # (C, T)
    wav_bytes = tensor_to_wav_bytes(tensor)

    buf = io.BytesIO(wav_bytes)
    data, sample_rate = sf.read(buf, dtype="float32")
    assert sample_rate == 24000
    assert data.ndim == 2
    assert data.shape == (12000, 2)


def test_tensor_to_pcm16_bytes():
    """Convert tensor to raw PCM int16 bytes (no WAV header)."""
    tensor = torch.randn(1, 100)
    pcm_bytes = tensor_to_pcm16_bytes(tensor)

    # Should be 2 bytes per sample (int16)
    assert len(pcm_bytes) == 100 * 2

    # Should NOT have WAV header
    assert pcm_bytes[:4] != b"RIFF"


def test_read_upload_bounded_valid():
    """Valid upload within size limit should pass."""
    data = b"x" * 1000
    result = read_upload_bounded(data, max_bytes=2000)
    assert result == data


def test_read_upload_bounded_empty():
    """Empty upload should raise ValueError."""
    with pytest.raises(ValueError, match="is empty"):
        read_upload_bounded(b"", max_bytes=1000)


def test_read_upload_bounded_too_large():
    """Upload exceeding size limit should raise ValueError."""
    data = b"x" * 3000
    with pytest.raises(ValueError, match="too large"):
        read_upload_bounded(data, max_bytes=2000)


def test_validate_audio_bytes_valid_wav():
    """Valid WAV bytes should pass validation."""
    # Create a minimal valid WAV
    tensor = torch.randn(1, 1000)
    buf = io.BytesIO()
    sf.write(buf, tensor.squeeze(0).numpy(), 24000, format="WAV", subtype="PCM_16")
    buf.seek(0)
    audio_bytes = buf.read()

    # Should not raise
    validate_audio_bytes(audio_bytes)


def test_validate_audio_bytes_invalid_format():
    """Invalid audio format should raise ValueError."""
    invalid_bytes = b"This is not audio data"

    with pytest.raises(ValueError, match="could not parse as audio file"):
        validate_audio_bytes(invalid_bytes)


def test_validate_audio_bytes_empty_audio():
    """Audio file with 0 frames should raise ValueError."""
    # Create WAV with 0 samples
    tensor = torch.randn(1, 0)
    buf = io.BytesIO()

    try:
        sf.write(buf, tensor.squeeze(0).numpy(), 24000, format="WAV", subtype="PCM_16")
    except (RuntimeError, OSError):
        pytest.skip("soundfile backend cannot write 0-frame WAV")

    buf.seek(0)
    audio_bytes = buf.read()

    # Different PyTorch versions return different error messages
    with pytest.raises(ValueError, match="has 0 frames|could not parse"):
        validate_audio_bytes(audio_bytes)


def test_validate_audio_bytes_low_sample_rate():
    """Audio with sample rate below 8000Hz should raise ValueError."""
    # Create audio at 4000Hz (too low)
    tensor = torch.randn(1, 1000)
    buf = io.BytesIO()
    sf.write(buf, tensor.squeeze(0).numpy(), 4000, format="WAV", subtype="PCM_16")
    buf.seek(0)
    audio_bytes = buf.read()

    with pytest.raises(ValueError, match="sample rate.*too low"):
        validate_audio_bytes(audio_bytes)


def test_validate_audio_bytes_custom_field_name():
    """Custom field name should appear in error messages."""
    invalid_bytes = b"not audio"

    with pytest.raises(ValueError, match="my_field"):
        validate_audio_bytes(invalid_bytes, field_name="my_field")
