"""
/v1/audio/script - Multi-speaker script synthesis endpoint
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from ..services.script import ScriptOrchestrator
from ..utils.audio import (
    SAMPLE_RATE,
    ResponseFormat,
    group_by_speaker,
    mix_to_single_track,
    tensor_to_wav_bytes,
    tensors_to_formatted_bytes,
)

router = APIRouter()

# Speaker ID validation regex: alphanumeric, underscore, hyphen, 1-64 chars
SPEAKER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ScriptSegment(BaseModel):
    """Single segment in a multi-speaker script."""

    speaker: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=10_000)
    voice: str | None = Field(default=None)
    speed: float | None = Field(default=None, ge=0.25, le=4.0)

    @field_validator("speaker")
    @classmethod
    def validate_speaker(cls, v: str) -> str:
        if not SPEAKER_ID_PATTERN.match(v):
            raise ValueError(
                f"Invalid speaker ID '{v}': must be 1-64 alphanumeric/underscore/hyphen characters"
            )
        return v

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text cannot be whitespace-only")
        return v

    @field_validator("voice")
    @classmethod
    def validate_voice(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Voice cannot be whitespace-only")
        return v


class ScriptRequest(BaseModel):
    """Request body for /v1/audio/script endpoint."""

    script: list[ScriptSegment] = Field(..., min_length=1, max_length=100)
    default_voice: str | None = Field(default=None)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    response_format: ResponseFormat = Field(default="wav")
    output_format: Literal["single_track", "multi_track"] = Field(default="single_track")
    pause_between_speakers: float = Field(default=0.5, ge=0.0, le=5.0)
    on_error: Literal["abort", "skip"] = Field(default="abort")

    @field_validator("script")
    @classmethod
    def validate_script(cls, v: list[ScriptSegment]) -> list[ScriptSegment]:
        # Check total character count
        total_chars = sum(len(seg.text) for seg in v)
        if total_chars > 50_000:
            raise ValueError(
                f"Total script length {total_chars} exceeds limit of 50,000 characters"
            )

        # Check unique speakers
        unique_speakers = len(set(seg.speaker for seg in v))
        if unique_speakers > 10:
            raise ValueError(f"Script has {unique_speakers} unique speakers, limit is 10")

        return v


@dataclass
class _ScriptAdapterRequest:
    """Adapter to map ScriptRequest to ScriptOrchestrator interface."""

    segments: list
    default_voice: str | None
    speed: float
    on_error: str
    insert_pause_ms: int


def _get_orchestrator(request: Request) -> ScriptOrchestrator:
    """Dependency injection for ScriptOrchestrator."""
    return request.app.state.script_orchestrator


@router.post("/audio/script")
async def create_script_audio(
    body: ScriptRequest,
    orchestrator: ScriptOrchestrator = Depends(_get_orchestrator),
):
    """
    Synthesize multi-speaker script with voice resolution and mixing.

    Returns either:
    - single_track: Binary audio with metadata headers
    - multi_track: JSON with per-speaker tracks and segment timestamps
    """
    # Create adapter request for orchestrator
    adapter = _ScriptAdapterRequest(
        segments=body.script,
        default_voice=body.default_voice,
        speed=body.speed,
        on_error=body.on_error,
        insert_pause_ms=int(body.pause_between_speakers * 1000),
    )

    # Synthesize script
    result = await orchestrator.synthesize_script(adapter)

    # Extract audio segments (filter out pause markers)
    audio_segments = [seg for seg in result.synthesized_segments if seg.get("type") == "audio"]

    segments_with_tensors = []
    for seg in audio_segments:
        if "speaker" not in seg or "audio" not in seg:
            raise RuntimeError(f"Malformed audio segment from orchestrator: {seg.keys()}")
        segments_with_tensors.append({"speaker": seg["speaker"], "audio": seg["audio"]})

    # Compute unique speakers and segment count
    unique_speakers = len(set(seg["speaker"] for seg in segments_with_tensors))
    segment_count = len(segments_with_tensors)

    # Format skipped segments header
    skipped_header = ",".join(map(str, result.skipped_indices)) if result.skipped_indices else ""

    try:
        if body.output_format == "single_track":
            # Mix to single track with pauses
            mixed_tensor, timestamps = mix_to_single_track(
                segments_with_tensors, pause_s=body.pause_between_speakers
            )

            # Convert to requested format
            audio_bytes, media_type = tensors_to_formatted_bytes(
                [mixed_tensor], body.response_format
            )

            # Compute total duration
            total_duration_s = mixed_tensor.shape[-1] / SAMPLE_RATE

            return Response(
                content=audio_bytes,
                media_type=media_type,
                headers={
                    "X-Audio-Duration-S": str(round(total_duration_s, 3)),
                    "X-Synthesis-Latency-S": str(round(result.total_latency_s, 3)),
                    "X-Speakers-Unique": str(unique_speakers),
                    "X-Segment-Count": str(segment_count),
                    "X-Skipped-Segments": skipped_header,
                },
            )

        # Group by speaker
        speaker_tracks = group_by_speaker(segments_with_tensors)

        # Encode each speaker's track to base64 WAV
        tracks_b64 = {}
        for speaker, tensor in speaker_tracks.items():
            wav_bytes = tensor_to_wav_bytes(tensor)
            tracks_b64[speaker] = base64.b64encode(wav_bytes).decode("utf-8")

        # Build segment timestamps (use mix_to_single_track for timestamp calculation)
        _, timestamps = mix_to_single_track(
            segments_with_tensors, pause_s=body.pause_between_speakers
        )

        # Compute total duration from the actual mixed timeline
        if timestamps:
            last = timestamps[-1]
            total_duration_s = last.offset_s + last.duration_s
        else:
            total_duration_s = 0.0

        return JSONResponse(
            content={
                "tracks": tracks_b64,
                "metadata": {
                    "total_duration_s": round(total_duration_s, 3),
                    "speakers_unique": unique_speakers,
                    "segment_count": segment_count,
                    "skipped_segments": result.skipped_indices,
                    "segments": [
                        {
                            "index": ts.index,
                            "speaker": ts.speaker,
                            "offset_s": round(ts.offset_s, 3),
                            "duration_s": round(ts.duration_s, 3),
                        }
                        for ts in timestamps
                    ],
                },
            },
            headers={
                "X-Synthesis-Latency-S": str(round(result.total_latency_s, 3)),
                "X-Speakers-Unique": str(unique_speakers),
                "X-Segment-Count": str(segment_count),
                "X-Skipped-Segments": skipped_header,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
