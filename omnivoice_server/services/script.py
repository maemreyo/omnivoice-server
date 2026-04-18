"""
Script synthesis orchestration service.

Handles multi-segment script synthesis with voice resolution, speaker inheritance,
pause insertion, and error handling strategies.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
from fastapi import HTTPException

from omnivoice_server.config import Settings
from omnivoice_server.services.inference import InferenceService, SynthesisRequest
from omnivoice_server.services.metrics import MetricsService
from omnivoice_server.services.profiles import ProfileNotFoundError, ProfileService
from omnivoice_server.voice_presets import OPENAI_VOICE_PRESETS

# Constants
MAX_SCRIPT_SEGMENTS = 100
MAX_TOTAL_INPUT_CHARS = 50_000
MAX_UNIQUE_SPEAKERS = 10
MAX_SEGMENT_CHARS = 10_000
SCRIPT_TOTAL_TIMEOUT_S = 600
MAX_TOTAL_AUDIO_DURATION_S = 600


@dataclass
class ScriptSegmentInput:
    """Input segment for script synthesis."""

    index: int
    speaker: str
    text: str
    voice: str | None = None
    speed: float | None = None


@dataclass
class ScriptResult:
    """Result of script synthesis."""

    synthesized_segments: list[dict[str, Any]] = field(default_factory=list)
    skipped_indices: list[int] = field(default_factory=list)
    timestamps: dict[str, float] = field(default_factory=dict)
    total_latency_s: float = 0.0


@dataclass(frozen=True)
class ResolvedVoice:
    """Resolved voice information for a speaker."""

    kind: str
    value: str
    ref_audio_path: Path | None = None


class ScriptMetrics:
    """Script-specific metrics wrapper."""

    def __init__(self, metrics_service: MetricsService):
        self._metrics = metrics_service
        self._lock = threading.Lock()
        self.requests_total = 0
        self.requests_success = 0
        self.requests_error = 0
        self.requests_timeout = 0
        self.segments_synthesized = 0
        self.segments_skipped = 0
        self.voice_resolution_failures = 0
        self._latencies: deque = deque(maxlen=200)

    def increment_requests_total(self) -> None:
        with self._lock:
            self.requests_total += 1

    def increment_requests_success(self) -> None:
        with self._lock:
            self.requests_success += 1

    def increment_requests_error(self) -> None:
        with self._lock:
            self.requests_error += 1

    def increment_requests_timeout(self) -> None:
        with self._lock:
            self.requests_timeout += 1

    def increment_segments_synthesized(self, count: int = 1) -> None:
        with self._lock:
            self.segments_synthesized += count

    def increment_segments_skipped(self, count: int = 1) -> None:
        with self._lock:
            self.segments_skipped += count

    def increment_voice_resolution_failures(self) -> None:
        with self._lock:
            self.voice_resolution_failures += 1

    def record_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(latency_ms)

    def snapshot(self) -> dict:
        """Return snapshot of all script metrics."""
        with self._lock:
            lats = list(self._latencies)
        mean_ms = sum(lats) / len(lats) if lats else 0.0
        sorted_lats = sorted(lats)
        p95_ms = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0

        return {
            "script_requests_total": self.requests_total,
            "script_requests_success": self.requests_success,
            "script_requests_error": self.requests_error,
            "script_requests_timeout": self.requests_timeout,
            "script_mean_latency_ms": round(mean_ms, 1),
            "script_p95_latency_ms": round(p95_ms, 1),
            "script_segments_synthesized": self.segments_synthesized,
            "script_segments_skipped": self.segments_skipped,
            "script_voice_resolution_failures": self.voice_resolution_failures,
        }


class ScriptOrchestrator:
    """Orchestrates multi-segment script synthesis."""

    def __init__(
        self,
        inference_service: InferenceService,
        profile_service: ProfileService,
        metrics_service: MetricsService,
        settings: Settings,
    ):
        self._inference = inference_service
        self._profiles = profile_service
        self._settings = settings
        self._metrics = ScriptMetrics(metrics_service)
        self._slot_lock = asyncio.Lock()

    @property
    def script_metrics(self) -> ScriptMetrics:
        """Expose script metrics for external access."""
        return self._metrics

    async def _resolve_voices(
        self,
        segments: list,
        default_voice: str | None,
    ) -> dict:
        """
        Resolve speaker→voice mapping using first-definition inheritance rule.

        Returns:
            dict mapping speaker names to voice identifiers

        Raises:
            HTTPException 422 if clone profile not found or OpenAI preset invalid
        """
        speaker_voices: dict[str, ResolvedVoice] = {}

        for segment in segments:
            speaker = segment.speaker

            # Skip if already resolved
            if speaker in speaker_voices:
                continue

            # Explicit voice on segment
            if segment.voice:
                voice = segment.voice
            # Inherit from default
            elif default_voice:
                voice = default_voice
            # Fall back to system default
            else:
                voice = self._settings.default_voice

            # Upfront validation for clone profiles
            if voice.startswith("clone:"):
                profile_id = voice.split(":", 1)[1]
                try:
                    ref_audio_path = self._profiles.get_ref_audio_path(profile_id)
                except ProfileNotFoundError:
                    self._metrics.increment_voice_resolution_failures()
                    raise HTTPException(
                        status_code=422, detail=f"Clone profile not found: {profile_id}"
                    )
                speaker_voices[speaker] = ResolvedVoice(
                    kind="clone",
                    value=profile_id,
                    ref_audio_path=ref_audio_path,
                )
                continue

            # Upfront validation for OpenAI presets
            if voice.startswith("openai:"):
                preset_name = voice.split(":", 1)[1]
                instruct = OPENAI_VOICE_PRESETS.get(preset_name)
                if not instruct:
                    self._metrics.increment_voice_resolution_failures()
                    raise HTTPException(
                        status_code=422, detail=f"Invalid OpenAI preset: {preset_name}"
                    )
                speaker_voices[speaker] = ResolvedVoice(kind="design", value=instruct)
                continue

            # Design voices validated lazily at synthesis time
            speaker_voices[speaker] = ResolvedVoice(kind="design", value=voice)

        return speaker_voices

    async def _build_synthesis_request(
        self,
        text: str,
        voice: ResolvedVoice,
        speed: float | None,
        base_speed: float,
    ) -> SynthesisRequest:
        """Build synthesis request using real SynthesisRequest dataclass."""
        # Use segment speed if provided, otherwise use base speed
        effective_speed = speed if speed is not None else base_speed

        # Parse voice type and construct appropriate SynthesisRequest
        if voice.kind == "clone":
            return SynthesisRequest(
                text=text,
                mode="clone",
                ref_audio_path=voice.ref_audio_path,
                ref_text=None,  # Optional, not provided in script context
                speed=effective_speed,
                num_step=None,  # Use server default
            )

        return SynthesisRequest(
            text=text,
            mode="design",
            instruct=voice.value,
            speed=effective_speed,
            num_step=None,  # Use server default
        )

    async def _synthesize_segments(
        self,
        segments: list,
        speaker_voices: dict,
        base_speed: float,
        on_error: str,
        insert_pause_ms: int,
    ) -> ScriptResult:
        """
        Synthesize segments with pause insertion and error handling.

        Args:
            segments: List of script segment inputs
            speaker_voices: Resolved speaker→voice mapping
            base_speed: Base speed from request
            on_error: Error handling strategy ('skip' or 'abort')
            insert_pause_ms: Pause duration on speaker change

        Returns:
            ScriptResult with synthesized segments and metadata
        """
        result = ScriptResult()
        prev_speaker: str | None = None

        for segment in segments:
            speaker = segment.speaker
            voice = speaker_voices[speaker]

            # Insert pause on speaker change
            if prev_speaker is not None and speaker != prev_speaker and insert_pause_ms > 0:
                result.synthesized_segments.append(
                    {
                        "type": "pause",
                        "duration_s": insert_pause_ms / 1000.0,
                    }
                )

            prev_speaker = speaker

            # Build synthesis request
            req = await self._build_synthesis_request(
                text=segment.text,
                voice=voice,
                speed=segment.speed,
                base_speed=base_speed,
            )

            try:
                synthesis_result = await self._inference.synthesize(req)
                if not synthesis_result.tensors or any(
                    t.numel() == 0 for t in synthesis_result.tensors
                ):
                    raise HTTPException(
                        status_code=500,
                        detail=f"Segment {segment.index} produced empty audio",
                    )
                audio_tensor = torch.cat(synthesis_result.tensors, dim=-1)

                result.synthesized_segments.append(
                    {
                        "type": "audio",
                        "index": segment.index,
                        "speaker": speaker,
                        "audio": audio_tensor,
                        "duration_s": synthesis_result.duration_s,
                        "voice": voice,
                    }
                )

                self._metrics.increment_segments_synthesized()

            except HTTPException:
                if on_error == "abort":
                    raise
                else:
                    result.skipped_indices.append(segment.index)
                    self._metrics.increment_segments_skipped()
            except Exception as e:
                if on_error == "abort":
                    raise HTTPException(
                        status_code=500,
                        detail=f"Segment {segment.index} synthesis failed: {str(e)}",
                    )
                else:
                    result.skipped_indices.append(segment.index)
                    self._metrics.increment_segments_skipped()

        return result

    async def synthesize_script(
        self,
        req: Any,  # Duck-typed ScriptSynthesisRequest to avoid circular import
    ) -> ScriptResult:
        """
        Synthesize multi-segment script with voice resolution and orchestration.

        Args:
            req: ScriptSynthesisRequest with segments, default_voice, speed, etc.

        Returns:
            ScriptResult with synthesized audio segments

        Raises:
            HTTPException 503 if synthesis at capacity
            HTTPException 422 if validation fails or all segments failed
            HTTPException 504 if total timeout exceeded
        """
        start_time = time.time()
        self._metrics.increment_requests_total()

        if self._slot_lock.locked():
            raise HTTPException(
                status_code=503,
                detail="Script synthesis at capacity — try again later",
            )

        try:
            async with self._slot_lock:
                # Convert segments to ScriptSegmentInput
                segments = [
                    ScriptSegmentInput(
                        index=i,
                        speaker=seg.speaker,
                        text=seg.text,
                        voice=seg.voice,
                        speed=seg.speed,
                    )
                    for i, seg in enumerate(req.segments)
                ]

                # Resolve voices upfront
                resolve_start = time.time()
                speaker_voices = await self._resolve_voices(
                    segments=segments,
                    default_voice=req.default_voice,
                )
                resolve_time = time.time() - resolve_start

                # Estimate total duration for memory budget check
                # Account for effective speed per segment: base_speed and per-segment overrides
                # Baseline: ~0.08s per char at speed=1.0 (more realistic than 0.05)
                # Adjust by effective speed: faster speed = shorter duration
                total_duration_estimate = 0.0
                for seg in segments:
                    effective_speed = seg.speed if seg.speed is not None else req.speed
                    char_count = len(seg.text)
                    # Duration = (chars * base_rate) / speed
                    segment_duration = (char_count * 0.08) / effective_speed
                    total_duration_estimate += segment_duration

                # Add pause contributions: (num_segments - 1) * pause_duration
                if len(segments) > 1:
                    pause_duration_s = req.insert_pause_ms / 1000.0
                    # Worst case: every segment has a different speaker
                    total_duration_estimate += (len(segments) - 1) * pause_duration_s

                if total_duration_estimate > MAX_TOTAL_AUDIO_DURATION_S:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Estimated duration {total_duration_estimate:.1f}s "
                            f"exceeds limit {MAX_TOTAL_AUDIO_DURATION_S}s"
                        ),
                    )

                # Synthesize segments with total timeout (Python 3.9+ compatible)
                synthesis_start = time.time()
                result = await asyncio.wait_for(
                    self._synthesize_segments(
                        segments=segments,
                        speaker_voices=speaker_voices,
                        base_speed=req.speed,
                        on_error=req.on_error,
                        insert_pause_ms=req.insert_pause_ms,
                    ),
                    timeout=SCRIPT_TOTAL_TIMEOUT_S,
                )
                synthesis_time = time.time() - synthesis_start

                # Check if all segments failed
                audio_segments = [s for s in result.synthesized_segments if s["type"] == "audio"]
                if not audio_segments:
                    raise HTTPException(status_code=422, detail="All segments failed synthesis")

                # Record timestamps
                result.timestamps = {
                    "voice_resolution_s": resolve_time,
                    "synthesis_s": synthesis_time,
                }

                # Record total latency
                total_latency = time.time() - start_time
                result.total_latency_s = total_latency
                self._metrics.record_latency(total_latency * 1000)
                self._metrics.increment_requests_success()

                return result

        except asyncio.TimeoutError:
            self._metrics.increment_requests_timeout()
            raise HTTPException(
                status_code=504,
                detail=f"Script synthesis exceeded timeout of {SCRIPT_TOTAL_TIMEOUT_S}s",
            )
        except HTTPException:
            self._metrics.increment_requests_error()
            raise
        except Exception as e:
            self._metrics.increment_requests_error()
            raise HTTPException(status_code=500, detail=f"Script synthesis failed: {str(e)}")
