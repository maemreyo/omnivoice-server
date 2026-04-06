"""
Audio encoding helpers.
All functions are pure (no side effects) and synchronous.
"""

from __future__ import annotations

# FIX: io and torchaudio were imported a second time in the middle of the file,
# after validate_audio_bytes. Moved all imports to top — single import block.
import io
import wave

import torch
import torchaudio

SAMPLE_RATE = 24_000


def tensor_to_wav_bytes(tensor: torch.Tensor) -> bytes:
    """
    Convert (1, T) float32 tensor to 16-bit PCM WAV bytes.
    """
    cpu_tensor = tensor.cpu()
    if cpu_tensor.dim() == 1:
        cpu_tensor = cpu_tensor.unsqueeze(0)

    buf = io.BytesIO()
    torchaudio.save(
        buf,
        cpu_tensor,
        SAMPLE_RATE,
        format="wav",
        encoding="PCM_S",
        bits_per_sample=16,
    )
    buf.seek(0)
    return buf.read()


def tensors_to_wav_bytes(tensors: list[torch.Tensor]) -> bytes:
    """
    Concatenate multiple (1, T) tensors into a single WAV.
    """
    if len(tensors) == 1:
        return tensor_to_wav_bytes(tensors[0])
    combined = torch.cat([t.cpu() for t in tensors], dim=-1)
    return tensor_to_wav_bytes(combined)


def tensor_to_pcm16_bytes(tensor: torch.Tensor) -> bytes:
    """
    Convert (1, T) float32 tensor to raw PCM int16 bytes.
    Used for streaming — no WAV header, continuous byte stream.
    """
    flat = tensor.squeeze(0).cpu()  # (T,)
    return (flat * 32767).clamp(-32768, 32767).to(torch.int16).numpy().tobytes()


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
        info = torchaudio.info(buf)
    except Exception as e:
        wav_metadata = _read_wav_metadata(data)
        if wav_metadata is not None:
            _validate_audio_metadata(
                num_frames=wav_metadata[0],
                sample_rate=wav_metadata[1],
                field_name=field_name,
            )
        if isinstance(e, ValueError):
            raise
        raise ValueError(
            f"{field_name}: could not parse as audio file. "
            "Supported formats: WAV, MP3, FLAC, OGG. "
            f"Original error: {e}"
        ) from e
    else:
        _validate_audio_metadata(
            num_frames=info.num_frames,
            sample_rate=info.sample_rate,
            field_name=field_name,
        )


def _validate_audio_metadata(num_frames: int, sample_rate: int, field_name: str) -> None:
    if num_frames == 0:
        raise ValueError(f"{field_name}: audio file has 0 frames")
    if sample_rate < 8000:
        raise ValueError(f"{field_name}: sample rate {sample_rate}Hz too low (min 8000Hz)")


def _read_wav_metadata(data: bytes) -> tuple[int, int] | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            return wav_file.getnframes(), wav_file.getframerate()
    except wave.Error:
        return None
