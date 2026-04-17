"""
Script synthesis orchestration service.

Handles multi-segment script synthesis with voice resolution, speaker inheritance,
pause insertion, and error handling strategies.
"""

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import HTTPException

from omnivoice_server.config import Settings
from omnivoice_server.services.inference import InferenceService
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
    voice: Optional[str] = None
    speed: Optional[float] = None


@dataclass
class ScriptResult:
    """Result of script synthesis."""

    synthesized_segments: list[dict[str, Any]] = field(default_factory=list)
    skipped_indices: list[int] = field(default_factory=list)
    timestamps: dict[str, float] = field(default_factory=dict)
    total_latency_s: float = 0.0


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
        self._semaphore = asyncio.Semaphore(1)

    async def _resolve_voices(
        self,
        segments: list,
        default_voice: Optional[str],
    ) -> dict:
        """
        Resolve speaker→voice mapping using first-definition inheritance rule.

        Returns:
            dict mapping speaker names to voice identifiers

        Raises:
            HTTPException 422 if clone profile not found or OpenAI preset invalid
        """
        speaker_voices: dict[str, str] = {}

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
                    # Validate profile exists
                    await self._profiles.get_ref_audio_path(profile_id)
                except ProfileNotFoundError:
                    self._metrics.increment_voice_resolution_failures()
                    raise HTTPException(
                        status_code=422, detail=f"Clone profile not found: {profile_id}"
                    )

            # Upfront validation for OpenAI presets
            elif voice.startswith("openai:"):
                preset_name = voice.split(":", 1)[1]
                if preset_name not in OPENAI_VOICE_PRESETS:
                    self._metrics.increment_voice_resolution_failures()
                    raise HTTPException(
                        status_code=422, detail=f"Invalid OpenAI preset: {preset_name}"
                    )

            # Design voices validated lazily at synthesis time

            speaker_voices[speaker] = voice

        return speaker_voices

    def _build_synthesis_request(
        self,
        text: str,
        voice: str,
        speed: Optional[float],
        base_speed: float,
    ) -> Any:
        """Build synthesis request object (duck-typed to avoid circular import)."""
        # Use segment speed if provided, otherwise use base speed
        effective_speed = speed if speed is not None else base_speed

        # Parse voice type
        if voice.startswith("clone:"):
            profile_id = voice.split(":", 1)[1]
            return type(
                "SynthesisRequest",
                (),
                {
                    "text": text,
                    "voice_type": "clone",
                    "clone_profile_id": profile_id,
                    "speed": effective_speed,
                    "openai_voice": None,
                    "design_voice_attrs": None,
                },
            )()
        elif voice.startswith("openai:"):
            preset_name = voice.split(":", 1)[1]
            return type(
                "SynthesisRequest",
                (),
                {
                    "text": text,
                    "voice_type": "openai",
                    "openai_voice": preset_name,
                    "speed": effective_speed,
                    "clone_profile_id": None,
                    "design_voice_attrs": None,
                },
            )()
        else:
            # Design voice (lazy validation)
            return type(
                "SynthesisRequest",
                (),
                {
                    "text": text,
                    "voice_type": "design",
                    "design_voice_attrs": {"voice_id": voice},
                    "speed": effective_speed,
                    "clone_profile_id": None,
                    "openai_voice": None,
                },
            )()

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
            segments: List of (speaker, segment) tuples
            speaker_voices: Resolved speaker→voice mapping
            base_speed: Base speed from request
            on_error: Error handling strategy ('skip' or 'abort')
            insert_pause_ms: Pause duration on speaker change

        Returns:
            ScriptResult with synthesized segments and metadata
        """
        result = ScriptResult()
        prev_speaker: Optional[str] = None

        for i, (speaker, segment) in enumerate(segments):
            voice = speaker_voices[speaker]

            # Insert pause on speaker change
            if prev_speaker is not None and speaker != prev_speaker and insert_pause_ms > 0:
                result.synthesized_segments.append(
                    {
                        "type": "pause",
                        "duration_ms": insert_pause_ms,
                    }
                )

            prev_speaker = speaker

            # Build synthesis request
            req = self._build_synthesis_request(
                text=segment.text,
                voice=voice,
                speed=segment.speed,
                base_speed=base_speed,
            )

            try:
                # Synthesize segment
                synthesis_result = await self._inference.synthesize(req)

                result.synthesized_segments.append(
                    {
                        "type": "audio",
                        "index": segment.index,
                        "speaker": speaker,
                        "audio_base64": synthesis_result.audio_base64,
                        "duration_ms": synthesis_result.duration_ms,
                        "voice": voice,
                    }
                )

                self._metrics.increment_segments_synthesized()

            except Exception as e:
                if on_error == "abort":
                    raise HTTPException(
                        status_code=500,
                        detail=f"Segment {segment.index} synthesis failed: {str(e)}",
                    )
                else:  # skip
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

        try:
            # Check semaphore capacity
            if self._semaphore.locked():
                raise HTTPException(
                    status_code=503, detail="Script synthesis at capacity — try again later"
                )

            async with self._semaphore:
                # Apply total timeout
                async with asyncio.timeout(SCRIPT_TOTAL_TIMEOUT_S):
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
                    total_chars = sum(len(seg.text) for seg in segments)
                    estimated_duration_s = total_chars * 0.05  # ~50ms per char

                    if estimated_duration_s > MAX_TOTAL_AUDIO_DURATION_S:
                        raise HTTPException(
                            status_code=422,
                            detail=f"Estimated duration {estimated_duration_s:.1f}s exceeds limit {MAX_TOTAL_AUDIO_DURATION_S}s",
                        )

                    # Synthesize segments
                    synthesis_start = time.time()
                    result = await self._synthesize_segments(
                        segments=[(seg.speaker, seg) for seg in segments],
                        speaker_voices=speaker_voices,
                        base_speed=req.speed,
                        on_error=req.on_error,
                        insert_pause_ms=req.insert_pause_ms,
                    )
                    synthesis_time = time.time() - synthesis_start

                    # Check if all segments failed
                    audio_segments = [
                        s for s in result.synthesized_segments if s["type"] == "audio"
                    ]
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
