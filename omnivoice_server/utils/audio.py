"""
Audio encoding helpers.
All functions are pure (no side effects) and synchronous.
"""

from __future__ import annotations

import io
import logging
import shutil
from dataclasses import dataclass
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


def validate_audio_tensor(tensor: torch.Tensor | np.ndarray, context: str = "audio") -> None:
    """
    Validate audio tensor shape and values before conversion.

    Args:
        tensor: Audio tensor to validate
        context: Context string for error messages

    Raises:
        ValueError: If tensor is malformed
    """
    if isinstance(tensor, np.ndarray):
        arr = tensor
    else:
        arr = tensor.detach().cpu().numpy()

    if arr.size == 0:
        raise ValueError(f"{context}: tensor is empty (size=0)")

    if arr.ndim > 2:
        raise ValueError(f"{context}: tensor has too many dimensions ({arr.ndim}), expected 1 or 2")

    if not np.isfinite(arr).all():
        raise ValueError(f"{context}: tensor contains NaN or Inf values")


def tensor_to_wav_bytes(tensor: torch.Tensor | np.ndarray) -> bytes:
    """
    Convert (1, T) float32 tensor or numpy array to 16-bit PCM WAV bytes.
    """
    validate_audio_tensor(tensor, "tensor_to_wav_bytes")

    if isinstance(tensor, np.ndarray):
        tensor = torch.from_numpy(tensor)
    cpu_tensor = tensor.detach().cpu()
    if cpu_tensor.dim() == 1:
        cpu_tensor = cpu_tensor.unsqueeze(0)

    if cpu_tensor.dim() == 2:
        if cpu_tensor.shape[0] == 1:
            cpu_tensor = cpu_tensor.squeeze(0)
        else:
            cpu_tensor = cpu_tensor.T

    buf = io.BytesIO()
    sf.write(buf, cpu_tensor.numpy(), SAMPLE_RATE, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


def tensors_to_wav_bytes(tensors: list[torch.Tensor | np.ndarray]) -> bytes:
    """
    Concatenate multiple (1, T) tensors into a single WAV.
    """
    if not tensors:
        raise ValueError("tensors_to_wav_bytes: empty tensor list")

    for i, t in enumerate(tensors):
        validate_audio_tensor(t, f"tensors_to_wav_bytes[{i}]")

    if len(tensors) == 1:
        return tensor_to_wav_bytes(tensors[0])

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
    validate_audio_tensor(tensor, "tensor_to_pcm16_bytes")

    if isinstance(tensor, np.ndarray):
        tensor = torch.from_numpy(tensor)
    flat = tensor.squeeze(0).detach().cpu()
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


@dataclass
class SegmentTimestamp:
    """Timestamp metadata for a single audio segment in a mixed track."""

    index: int
    speaker: str
    offset_s: float
    duration_s: float


def make_silence_tensor(duration_s: float, sample_rate: int = SAMPLE_RATE) -> torch.Tensor:
    """
    Create a silent audio tensor of specified duration.

    Args:
        duration_s: Duration in seconds
        sample_rate: Sample rate in Hz (default: 24000)

    Returns:
        torch.Tensor: Shape (1, num_samples) of zeros
    """
    num_samples = int(duration_s * sample_rate)
    return torch.zeros(1, num_samples)


def mix_to_single_track(
    segments: list[dict],
    pause_s: float = 0.5,
) -> tuple[torch.Tensor, list[SegmentTimestamp]]:
    """
    Concatenate audio segments into a single track with pauses on speaker change.

    Args:
        segments: List of dicts with keys:
            - 'audio': torch.Tensor (1, T)
            - 'speaker': str
        pause_s: Pause duration in seconds when speaker changes

    Returns:
        Tuple of:
            - Mixed audio tensor (1, total_samples)
            - List of SegmentTimestamp metadata
    """
    if not segments:
        return torch.zeros(1, 0), []

    for idx, seg in enumerate(segments):
        if "audio" not in seg:
            raise ValueError(f"mix_to_single_track: segment {idx} missing 'audio' key")
        validate_audio_tensor(seg["audio"], f"mix_to_single_track segment {idx}")

    chunks: list[torch.Tensor] = []
    timestamps: list[SegmentTimestamp] = []
    offset_s = 0.0
    prev_speaker = None

    for idx, seg in enumerate(segments):
        audio = seg["audio"]
        speaker = seg["speaker"]

        if prev_speaker is not None and speaker != prev_speaker:
            silence = make_silence_tensor(pause_s)
            chunks.append(silence)
            offset_s += pause_s

        duration_s = audio.shape[-1] / SAMPLE_RATE
        timestamps.append(
            SegmentTimestamp(
                index=idx,
                speaker=speaker,
                offset_s=offset_s,
                duration_s=duration_s,
            )
        )

        chunks.append(audio)
        offset_s += duration_s
        prev_speaker = speaker

    mixed = torch.cat(chunks, dim=-1)
    return mixed, timestamps


def group_by_speaker(segments: list[dict]) -> dict[str, torch.Tensor]:
    """
    Group audio segments by speaker and concatenate each speaker's audio.

    Args:
        segments: List of dicts with keys:
            - 'audio': torch.Tensor (1, T)
            - 'speaker': str

    Returns:
        Dict mapping speaker ID to concatenated audio tensor
    """
    for idx, seg in enumerate(segments):
        if "audio" not in seg:
            raise ValueError(f"group_by_speaker: segment {idx} missing 'audio' key")
        validate_audio_tensor(seg["audio"], f"group_by_speaker segment {idx}")

    speaker_groups: dict[str, list[torch.Tensor]] = {}

    for seg in segments:
        speaker = seg["speaker"]
        audio = seg["audio"]

        if speaker not in speaker_groups:
            speaker_groups[speaker] = []
        speaker_groups[speaker].append(audio)

    return {speaker: torch.cat(audios, dim=-1) for speaker, audios in speaker_groups.items()}


# ── Degenerate output detection ──────────────────────────────────────────────
#
# OmniVoice sometimes returns audio that is technically valid — finite, right
# shape, right length — but contains no speech: a steady low-frequency drone
# (issue #37). It shows up when several non-verbal tags share one short
# utterance.
#
# Detecting it by loudness does not work, and an earlier version of this code
# that tried was ineffective. Measured against the real model, the reported
# failure runs at RMS 2500-12000 with only 2.7% of frames quiet — it is loud and
# steady, not silent. What distinguishes it is *frequency content*: speech at
# 24kHz crosses zero at roughly 0.05-0.25 of samples, while the drone sits near
# zero because it has almost no energy above a few tens of Hz.
#
# Zero-crossing rate separates them cleanly. Measured on k2-fsa/OmniVoice,
# scoring the fraction of audible windows that look like speech:
#
#   plain text, any length              0.50 - 1.00
#   one tag, 13 words                   0.80 - 0.94
#   one tag, 7 words                    0.25 - 0.73
#   one tag, 3 words                    0.00 - 0.14
#   three tags, 8 words (the report)    0.00 across 12 samples
#
# The governing variable is ordinary text per tag, not tag count or tag
# identity, and no generation parameter avoids it — num_step 8/16/32 and
# position_temperature=0 all failed on the reported input. Callers are warned
# rather than silently retried: there is nothing to retry to.

DEGENERATE_FRAME_MS = 250

# Below this, a window has too little high-frequency content to be speech.
# Whispering raises ZCR (it is noisier than voiced speech), so this threshold
# does not endanger the `whisper` design style.
SPEECH_ZCR_THRESHOLD = 0.04

# A window this quiet is scored as neither speech nor drone — it is a pause, and
# pauses should not count against an otherwise healthy generation.
SILENCE_RMS = 0.005


def _to_numpy_1d(tensor: torch.Tensor | np.ndarray) -> np.ndarray:
    """Flatten an audio tensor/array to 1-D float32 numpy, detaching if needed."""
    if torch.is_tensor(tensor):
        arr = tensor.detach().to("cpu", torch.float32).numpy()
    else:
        arr = np.asarray(tensor, dtype=np.float32)
    return arr.reshape(-1)


def _concat(tensors: list[torch.Tensor | np.ndarray]) -> np.ndarray:
    flat = [_to_numpy_1d(t) for t in tensors]
    if not flat:
        return np.zeros(0, dtype=np.float32)
    signal = np.concatenate(flat) if len(flat) > 1 else flat[0]
    # NaN would poison every comparison below; treat non-finite samples as zero.
    return np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)


def speech_window_ratio(
    tensors: list[torch.Tensor | np.ndarray],
    frame_ms: int = DEGENERATE_FRAME_MS,
    sample_rate: int = SAMPLE_RATE,
    zcr_threshold: float = SPEECH_ZCR_THRESHOLD,
    silence_rms: float = SILENCE_RMS,
) -> float:
    """
    Fraction of audible windows whose zero-crossing rate looks like speech.

    Near-silent windows are excluded from both numerator and denominator, so
    leading silence and inter-sentence pauses neither help nor hurt the score.
    Returns 1.0 when there is nothing audible to judge, so callers never treat
    "no signal to measure" as a failure.
    """
    signal = _concat(tensors)
    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = signal.shape[0] // frame_len
    if n_frames == 0:
        return 1.0

    frames = signal[: n_frames * frame_len].reshape(n_frames, frame_len)
    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    audible = frames[frame_rms >= silence_rms]
    if audible.shape[0] == 0:
        return 1.0

    # Zero crossings per window, as a fraction of samples in the window.
    signs = np.sign(audible)
    crossings = np.count_nonzero(np.diff(signs, axis=1) != 0, axis=1)
    zcr = crossings / audible.shape[1]

    return float(np.count_nonzero(zcr >= zcr_threshold) / audible.shape[0])


def is_degenerate_audio(
    tensors: list[torch.Tensor | np.ndarray],
    min_speech_ratio: float,
    min_duration_s: float = 1.0,
    sample_rate: int = SAMPLE_RATE,
) -> bool:
    """
    Report whether a generation contains speech, or only a low-frequency drone.

    Short outputs are never flagged: there are too few windows to judge, and a
    one-word render is legitimately dominated by onset and decay.
    """
    if not tensors:
        return False

    total_samples = sum(_to_numpy_1d(t).shape[0] for t in tensors)
    if total_samples < min_duration_s * sample_rate:
        return False

    return speech_window_ratio(tensors, sample_rate=sample_rate) < min_speech_ratio
