"""
Audio encoding helpers.
All functions are pure (no side effects) and synchronous.
"""

from __future__ import annotations

import io
import logging
import shutil
from typing import Literal

import numpy as np
import soundfile as sf
import torch

try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    AudioSegment = None  # type: ignore[misc,assignment]

# Cached at module load time - will not update if ffmpeg is installed/uninstalled at runtime
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

logger = logging.getLogger(__name__)
SAMPLE_RATE = 24_000

# Supported output formats per OpenAI API spec
ResponseFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


def tensor_to_wav_bytes(tensor: torch.Tensor | np.ndarray) -> bytes:
    """
    Convert (1, T) float32 tensor or numpy array to 16-bit PCM WAV bytes.
    """
    # Handle both torch.Tensor and numpy.ndarray (e.g., when running on CUDA)
    if isinstance(tensor, np.ndarray):
        tensor = torch.from_numpy(tensor)
    cpu_tensor = tensor.detach().cpu()
    if cpu_tensor.dim() == 1:
        cpu_tensor = cpu_tensor.unsqueeze(0)

    if cpu_tensor.dim() == 2:
        if cpu_tensor.shape[0] == 1:
            cpu_tensor = cpu_tensor.squeeze(0)  # (T,) mono
        else:
            cpu_tensor = cpu_tensor.T  # (C, T) -> (T, C)

    buf = io.BytesIO()
    sf.write(buf, cpu_tensor.numpy(), SAMPLE_RATE, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


def tensors_to_wav_bytes(tensors: list[torch.Tensor | np.ndarray]) -> bytes:
    """
    Concatenate multiple (1, T) tensors into a single WAV.
    """
    if len(tensors) == 1:
        return tensor_to_wav_bytes(tensors[0])
    # Convert numpy arrays to tensors if needed, then concatenate
    tensor_list = []
    for t in tensors:
        if isinstance(t, np.ndarray):
            t = torch.from_numpy(t)
        tensor_list.append(t.cpu())
    combined = torch.cat(tensor_list, dim=-1)
    return tensor_to_wav_bytes(combined)


def tensor_to_pcm16_bytes(tensor: torch.Tensor | np.ndarray) -> bytes:
    """
    Convert (1, T) float32 tensor or numpy array to raw PCM int16 bytes.
    Used for streaming — no WAV header, continuous byte stream.
    """
    # Handle both torch.Tensor and numpy.ndarray (e.g., when running on CUDA)
    if isinstance(tensor, np.ndarray):
        tensor = torch.from_numpy(tensor)
    flat = tensor.squeeze(0).detach().cpu()  # (T,)
    return (flat * 32767).clamp(-32768, 32767).to(torch.int16).numpy().tobytes()


def _convert_wav_to_format(wav_bytes: bytes, output_format: str) -> bytes:
    """Convert WAV bytes to target format using pydub.

    Args:
        wav_bytes: Valid WAV file bytes
        output_format: Target format (mp3, opus, aac, flac)

    Returns:
        Encoded audio bytes in target format

    Raises:
        RuntimeError: If pydub is not available or conversion fails
    """
    if not PYDUB_AVAILABLE:
        raise RuntimeError(
            f"Audio format '{output_format}' requires pydub and ffmpeg. "
            "Install with: pip install pydub  (also requires ffmpeg on PATH)"
        )

    # Verify ffmpeg is available on PATH
    if not FFMPEG_AVAILABLE:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg: https://ffmpeg.org/download.html"
        )

    # Map format names and parameters (mp3, opus, aac, flac only)
    format_map = {
        "mp3": {"format": "mp3", "bitrate": "128k"},
        "opus": {"format": "opus", "bitrate": "128k"},
        "aac": {"format": "adts", "bitrate": "128k"},
        "flac": {"format": "flac"},
    }

    if output_format not in format_map:
        raise ValueError(f"Unsupported output format: {output_format}")

    try:
        audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))
        output_buf = io.BytesIO()
        export_kwargs = format_map[output_format].copy()
        fmt = export_kwargs.pop("format")
        audio.export(output_buf, format=fmt, **export_kwargs)
        output_buf.seek(0)
        return output_buf.read()
    except Exception as e:
        raise RuntimeError(f"Audio conversion to {output_format} failed: {e}") from e


def tensors_to_formatted_bytes(
    tensors: list[torch.Tensor | np.ndarray],
    response_format: ResponseFormat,
) -> tuple[bytes, str]:
    """Convert tensors to audio bytes in specified format with media type.

    Args:
        tensors: List of audio tensors
        response_format: Target format (mp3, opus, aac, flac, wav, pcm)

    Returns:
        Tuple of (audio_bytes, media_type)

    Raises:
        RuntimeError: If pydub/ffmpeg not available or conversion fails
    """
    if response_format == "pcm":
        audio_bytes = b"".join(tensor_to_pcm16_bytes(t) for t in tensors)
        return audio_bytes, "audio/pcm"

    # Generate WAV first
    wav_bytes = tensors_to_wav_bytes(tensors)

    if response_format == "wav":
        return wav_bytes, "audio/wav"

    # Convert to other formats using pydub
    converted = _convert_wav_to_format(wav_bytes, response_format)

    media_types = {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
    }

    media_type = media_types.get(response_format)
    if media_type is None:
        raise ValueError(f"Unsupported format for media type: {response_format}")
    return converted, media_type


def read_upload_bounded(data: bytes, max_bytes: int, field_name: str = "ref_audio") -> bytes:
    """
    Validates upload size after reading.
    """
    if len(data) == 0:
        raise ValueError(f"{field_name} is empty")
    if len(data) > max_bytes:
        mb = len(data) / 1024 / 1024
        limit_mb = max_bytes / 1024 / 1024
        raise ValueError(f"{field_name} too large: {mb:.1f} MB (limit: {limit_mb:.0f} MB)")
    return data


def validate_audio_bytes(data: bytes, field_name: str = "ref_audio") -> None:
    """
    Lightweight validation: check that bytes are parseable as audio.
    Does NOT decode the full file — only reads metadata.
    """
    try:
        buf = io.BytesIO(data)
        info = sf.info(buf)
        if info.frames == 0:
            raise ValueError(f"{field_name}: audio file has 0 frames")
        if info.samplerate < 8000:
            raise ValueError(f"{field_name}: sample rate {info.samplerate}Hz too low (min 8000Hz)")
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(
            f"{field_name}: could not parse as audio file. "
            "Supported formats: WAV, MP3, FLAC, OGG. "
            f"Original error: {e}"
        ) from e
