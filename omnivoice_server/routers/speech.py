"""
/v1/audio/speech        - OpenAI-compatible TTS (instructions-driven design)
/v1/audio/speech/clone  - One-shot voice cloning (multipart upload)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..services.inference import InferenceService, SynthesisRequest, SynthesisResult
from ..services.metrics import MetricsService
from ..services.metrics import StreamObservation
from ..services.profiles import ProfileNotFoundError, ProfileService
from ..utils.audio import (
    ResponseFormat,
    tensor_to_pcm16_bytes,
    tensors_to_formatted_bytes,
)
from ..utils.instruction_validation import (
    InstructionValidationError,
    validate_and_canonicalize_instructions,
)
from ..utils.text import split_sentences
from ..voice_presets import (
    DEFAULT_DESIGN_INSTRUCTIONS,
    get_openai_voice_preset,
    is_openai_voice_preset,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SpeechRequest(BaseModel):
    """OpenAI TTS API compatible request body."""

    model: str = Field(default="omnivoice")
    input: str = Field(..., min_length=1, max_length=10_000)
    voice: str = Field(default="auto")
    speaker: str | None = Field(default=None)
    instructions: str | None = Field(default=None)
    response_format: ResponseFormat = Field(default="wav")
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    stream: bool = Field(default=False)
    num_step: int | None = Field(default=None, ge=1, le=64)
    guidance_scale: float | None = Field(default=None, ge=0.0, le=10.0)
    denoise: bool | None = Field(default=None)
    t_shift: float | None = Field(default=None, ge=0.0, le=2.0)
    position_temperature: float | None = Field(default=None, ge=0.0, le=10.0)
    class_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    duration: float | None = Field(default=None, ge=0.1, le=60.0)
    language: str | None = Field(
        default=None,
        description="Language code (e.g., 'en', 'vi', 'zh') for multilingual pronunciation",
    )
    layer_penalty_factor: float | None = Field(default=None, ge=0.0)
    preprocess_prompt: bool | None = Field(default=None)
    postprocess_output: bool | None = Field(default=None)
    audio_chunk_duration: float | None = Field(default=None, gt=0.0)
    audio_chunk_threshold: float | None = Field(default=None, gt=0.0)
    request_timeout_s: int | None = Field(default=None, ge=1, le=600)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if v not in ("omnivoice", "tts-1", "tts-1-hd"):
            logger.debug(f"model='{v}' mapped to omnivoice")
        return v


def _get_inference(request: Request) -> InferenceService:
    return request.app.state.inference_svc


def _get_profiles(request: Request) -> ProfileService:
    return request.app.state.profile_svc


def _get_metrics(request: Request) -> MetricsService:
    return request.app.state.metrics_svc


def _get_cfg(request: Request):
    return request.app.state.cfg


def _effective_timeout_s(request_timeout_s: int | None, cfg) -> int:
    return request_timeout_s or cfg.request_timeout_s


def _pcm_stream_response(
    stream_iter: AsyncIterator[bytes], request_id: str | None = None
) -> StreamingResponse:
    headers = {
        "X-Audio-Sample-Rate": "24000",
        "X-Audio-Channels": "1",
        "X-Audio-Bit-Depth": "16",
        "X-Audio-Format": "pcm-int16-le",
    }
    if request_id:
        headers["X-Request-Id"] = request_id
    return StreamingResponse(
        stream_iter,
        media_type="audio/pcm",
        headers=headers,
    )


def _resolve_synthesis_mode(
    body: SpeechRequest,
    profile_svc: ProfileService,
) -> tuple[str, str | None, str | None, str | None]:
    """Resolve synthesis mode for /v1/audio/speech."""
    logger.debug(
        "[TRACE] _resolve_synthesis_mode called: speaker=%r, voice=%r, instructions=%r",
        body.speaker,
        body.voice,
        body.instructions,
    )
    speaker_raw = body.speaker.strip() if body.speaker else None
    voice_raw = body.voice.strip() if body.voice else None

    speaker_key = speaker_raw.strip().lower() if speaker_raw else None
    voice_key = voice_raw.strip().lower() if voice_raw else None

    speaker_preset = get_openai_voice_preset(speaker_key)
    voice_preset = get_openai_voice_preset(voice_key)

    if speaker_raw and voice_raw:
        speaker_clone = speaker_raw.lower().startswith("clone:")
        voice_clone = voice_raw.lower().startswith("clone:")
        if speaker_clone != voice_clone:
            logger.warning(
                "[TRACE] Ambiguous voice request: speaker=%r, voice=%r mix clone/non-clone",
                body.speaker,
                body.voice,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Ambiguous request: `speaker` and `voice` use different resolution modes. "
                    "Use only one field, or make both refer to the same clone/preset choice."
                ),
            )
        if speaker_preset and voice_preset and speaker_preset != voice_preset:
            logger.warning(
                "[TRACE] Ambiguous preset request: speaker=%r -> %r, voice=%r -> %r",
                body.speaker,
                speaker_preset,
                body.voice,
                voice_preset,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Ambiguous request: `speaker` and `voice` resolve to different preset voices. "
                    "Use only one field."
                ),
            )

    profile_to_check = speaker_raw or voice_raw
    if profile_to_check:
        profile_id = profile_to_check
        explicit_clone = profile_id.lower().startswith("clone:")
        if explicit_clone:
            profile_id = profile_id.split(":", 1)[1]
            logger.debug(f"[TRACE] clone: prefix detected, extracted profile_id={profile_id!r}")
        try:
            ref_audio_path = profile_svc.get_ref_audio_path(profile_id)
            ref_text = profile_svc.get_ref_text(profile_id)
            logger.info(
                "[TRACE] Resolved to CLONE mode: profile_id=%r, ref_audio=%s",
                profile_id,
                ref_audio_path,
            )
            return "clone", None, str(ref_audio_path), ref_text
        except ProfileNotFoundError:
            if explicit_clone:
                logger.warning(f"[TRACE] Clone profile not found: {profile_id!r}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Voice profile '{profile_id}' not found. "
                    "Create it via POST /v1/audio/voices/profiles first.",
                )
            logger.debug(
                f"[TRACE] Profile '{profile_id}' not found; falling back to design/preset mode"
            )

    if speaker_raw and not speaker_preset and not speaker_raw.lower().startswith("clone:"):
        logger.warning(
            "[TRACE] Unrecognized speaker value=%r; use preset/clone or omit",
            body.speaker,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unsupported speaker value '{body.speaker}'. "
                "Use a known preset, clone:<profile_id>, "
                "or omit `speaker` and use `voice`/`instructions`."
            ),
        )

    if body.instructions is not None:
        try:
            canonicalized = validate_and_canonicalize_instructions(body.instructions)
            logger.info(f"[TRACE] Resolved to DESIGN mode (instructions): {canonicalized}")
            return "design", canonicalized, None, None
        except InstructionValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e),
            )

    if speaker_preset:
        preset_instruct = speaker_preset
        logger.info(
            "[TRACE] Resolved to DESIGN (speaker preset): speaker=%r -> %s",
            speaker_key,
            preset_instruct,
        )
        return "design", preset_instruct, None, None

    if voice_preset:
        preset_instruct = voice_preset
        logger.info(
            "[TRACE] Resolved to DESIGN (voice preset): voice=%r -> %s",
            voice_key,
            preset_instruct,
        )
        return "design", preset_instruct, None, None

    if voice_raw:
        design_voice = voice_raw
        if voice_raw.lower().startswith("design:"):
            design_voice = voice_raw.split(":", 1)[1]
        try:
            canonicalized = validate_and_canonicalize_instructions(design_voice)
            logger.info(f"[TRACE] Resolved to DESIGN mode (voice instructions): {canonicalized}")
            return "design", canonicalized, None, None
        except InstructionValidationError as e:
            if voice_raw.lower() == "auto":
                logger.info(
                    f"[TRACE] Resolved to DESIGN mode (default): {DEFAULT_DESIGN_INSTRUCTIONS}"
                )
                return "design", DEFAULT_DESIGN_INSTRUCTIONS, None, None
            if not is_openai_voice_preset(voice_raw):
                logger.warning(
                    "[TRACE] Unsupported voice value=%r; rejecting instead of silent fallback",
                    body.voice,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"Unsupported voice value '{body.voice}'. "
                        "Use a known preset, clone:<profile_id>, "
                        "or supported design attributes from /v1/voices."
                    ),
                ) from e

    logger.info(f"[TRACE] Resolved to DESIGN mode (default): {DEFAULT_DESIGN_INSTRUCTIONS}")
    return "design", DEFAULT_DESIGN_INSTRUCTIONS, None, None


def _extract_clone_profile_id(voice_str: str) -> str | None:
    voice = voice_str.strip()
    if not voice.startswith("clone:"):
        return None
    profile_id = voice[len("clone:") :].strip()
    return profile_id or None


@router.post("/audio/speech")
async def create_speech(
    body: SpeechRequest,
    inference_svc: InferenceService = Depends(_get_inference),
    profile_svc: ProfileService = Depends(_get_profiles),
    metrics_svc: MetricsService = Depends(_get_metrics),
    cfg=Depends(_get_cfg),
):
    """Generate speech from text."""
    mode, instruct, ref_audio_path, ref_text = _resolve_synthesis_mode(body, profile_svc)
    profile_id = _extract_clone_profile_id(body.voice)

    req = SynthesisRequest(
        text=body.input,
        mode=mode,
        instruct=instruct,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
        profile_id=profile_id,
        speed=body.speed,
        num_step=body.num_step,
        guidance_scale=body.guidance_scale,
        denoise=body.denoise,
        t_shift=body.t_shift,
        position_temperature=body.position_temperature,
        class_temperature=body.class_temperature,
        duration=body.duration,
        language=body.language,
        layer_penalty_factor=body.layer_penalty_factor,
        preprocess_prompt=body.preprocess_prompt,
        postprocess_output=body.postprocess_output,
        audio_chunk_duration=body.audio_chunk_duration,
        audio_chunk_threshold=body.audio_chunk_threshold,
    )

    if body.stream or cfg.stream:
        request_id = uuid.uuid4().hex[:12]
        # Streaming only supports PCM
        # (WAV streaming requires implementation of streaming RIFF headers)
        if body.response_format not in {"pcm", "wav"} or (
            cfg.stream and body.response_format != "pcm"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Streaming only supports response_format='pcm', got '{body.response_format}'"
                ),
            )
        stream_iter = (
            _stream_sentences_overlapped(body.input, req, inference_svc, metrics_svc, cfg)
            if cfg.stream_overlap
            else _stream_sentences(
                body.input,
                req,
                inference_svc,
                metrics_svc,
                cfg,
                request_id,
                profile_id,
            )
        )
        return _pcm_stream_response(stream_iter, request_id)

    timeout_s = _effective_timeout_s(body.request_timeout_s, cfg)

    try:
        if body.request_timeout_s is not None:
            result = await inference_svc.synthesize(req, timeout_override=body.request_timeout_s)
        else:
            result = await inference_svc.synthesize(req)
        metrics_svc.record_success(result.latency_s)
    except asyncio.TimeoutError:
        metrics_svc.record_timeout()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Synthesis timed out after {timeout_s}s",
        )
    except Exception as e:
        metrics_svc.record_error()
        logger.exception("Synthesis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {e}",
        )

    # Generate audio in requested format
    try:
        audio_bytes, media_type = tensors_to_formatted_bytes(result.tensors, body.response_format)
    except RuntimeError as e:
        # Format not available (e.g., pydub or ffmpeg missing)
        logger.warning(f"Format conversion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Audio format '{body.response_format}' not available: {e}",
        )

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "X-Audio-Duration-S": str(round(result.duration_s, 3)),
            "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
        },
    )


def _chunk_request(sentence: str, base_req: SynthesisRequest) -> SynthesisRequest:
    return SynthesisRequest(
        text=sentence,
        mode=base_req.mode,
        instruct=base_req.instruct,
        ref_audio_path=base_req.ref_audio_path,
        ref_text=base_req.ref_text,
        speed=base_req.speed,
        num_step=base_req.num_step,
        guidance_scale=base_req.guidance_scale,
        denoise=base_req.denoise,
        t_shift=base_req.t_shift,
        position_temperature=base_req.position_temperature,
        class_temperature=base_req.class_temperature,
        duration=base_req.duration,
        language=base_req.language,
        layer_penalty_factor=base_req.layer_penalty_factor,
        preprocess_prompt=base_req.preprocess_prompt,
        postprocess_output=base_req.postprocess_output,
        audio_chunk_duration=base_req.audio_chunk_duration,
        audio_chunk_threshold=base_req.audio_chunk_threshold,
    )


async def _stream_sentences(
    text: str,
    base_req: SynthesisRequest,
    inference_svc: InferenceService,
    metrics_svc: MetricsService,
    cfg,
    request_id: str,
    profile_id: str | None,
) -> AsyncIterator[bytes]:
    """Sentence-level streaming generator."""
    stream_started = time.monotonic()
    sentences = split_sentences(
        text,
        max_chars=cfg.stream_chunk_max_chars,
        eager_first_chunk=True,
    )
    sentence_split_ms = (time.monotonic() - stream_started) * 1000

    if not sentences:
        return

    first_chunk_chars = len(sentences[0])
    completed_synthesis_calls = 0
    emitted_audio_chunks = 0
    emitted_bytes = 0
    ttfa_ms: float | None = None
    first_synthesis_ms: float | None = None
    first_clone_prompt_ms: float | None = None
    first_decode_postprocess_ms: float | None = None
    first_postprocess_ms: float | None = None
    first_decode_only_ms: float | None = None
    first_cleanup_ms: float | None = None
    first_pcm_encode_ms: float | None = None
    first_prepare_inference_calls: int | None = None
    first_batch_size: int | None = None
    first_max_condition_len: int | None = None
    first_max_target_tokens: int | None = None
    first_max_ref_audio_tokens: int | None = None
    first_attention_mask_mb_estimate: float | None = None
    first_batch_logits_mb_estimate: float | None = None
    first_tokens_mb_estimate: float | None = None
    first_cuda_allocated_before_mb: float | None = None
    first_cuda_allocated_after_mb: float | None = None
    first_cuda_reserved_before_mb: float | None = None
    first_cuda_reserved_after_mb: float | None = None
    first_cuda_free_before_mb: float | None = None
    first_cuda_free_after_mb: float | None = None
    first_cuda_total_mb: float | None = None

    for sentence in sentences:
        req = _chunk_request(sentence, base_req)
        try:
            synth_started = time.monotonic()
            result = await inference_svc.synthesize(req)
            completed_synthesis_calls += 1
            if first_synthesis_ms is None:
                first_synthesis_ms = (time.monotonic() - synth_started) * 1000
                if result.breakdown is not None:
                    first_clone_prompt_ms = result.breakdown.clone_prompt_ms
                    first_decode_postprocess_ms = result.breakdown.decode_postprocess_ms
                    first_postprocess_ms = result.breakdown.postprocess_ms
                    first_decode_only_ms = result.breakdown.decode_only_ms
                    first_cleanup_ms = result.breakdown.cleanup_ms
                    first_prepare_inference_calls = result.breakdown.prepare_inference_calls
                    first_batch_size = result.breakdown.batch_size
                    first_max_condition_len = result.breakdown.max_condition_len
                    first_max_target_tokens = result.breakdown.max_target_tokens
                    first_max_ref_audio_tokens = result.breakdown.max_ref_audio_tokens
                    first_attention_mask_mb_estimate = (
                        result.breakdown.attention_mask_mb_estimate
                    )
                    first_batch_logits_mb_estimate = result.breakdown.batch_logits_mb_estimate
                    first_tokens_mb_estimate = result.breakdown.tokens_mb_estimate
                    first_cuda_allocated_before_mb = result.breakdown.cuda_allocated_before_mb
                    first_cuda_allocated_after_mb = result.breakdown.cuda_allocated_after_mb
                    first_cuda_reserved_before_mb = result.breakdown.cuda_reserved_before_mb
                    first_cuda_reserved_after_mb = result.breakdown.cuda_reserved_after_mb
                    first_cuda_free_before_mb = result.breakdown.cuda_free_before_mb
                    first_cuda_free_after_mb = result.breakdown.cuda_free_after_mb
                    first_cuda_total_mb = result.breakdown.cuda_total_mb

            for tensor in result.tensors:
                encode_started = time.monotonic()
                chunk = tensor_to_pcm16_bytes(tensor)
                encode_ms = (time.monotonic() - encode_started) * 1000
                emitted_audio_chunks += 1
                emitted_bytes += len(chunk)

                if first_pcm_encode_ms is None:
                    first_pcm_encode_ms = encode_ms
                if ttfa_ms is None:
                    ttfa_ms = (time.monotonic() - stream_started) * 1000

                yield chunk
        except asyncio.TimeoutError:
            total_ms = (time.monotonic() - stream_started) * 1000
            metrics_svc.record_timeout()
            observation = _build_stream_observation(
                request_id=request_id,
                mode=base_req.mode,
                profile_id=profile_id,
                input_chars=len(text),
                planned_synthesis_calls=len(sentences),
                first_chunk_chars=first_chunk_chars,
                completed_synthesis_calls=completed_synthesis_calls,
                emitted_audio_chunks=emitted_audio_chunks,
                emitted_bytes=emitted_bytes,
                status="timeout",
                sentence_split_ms=sentence_split_ms,
                ttfa_ms=ttfa_ms,
                first_synthesis_ms=first_synthesis_ms,
                first_clone_prompt_ms=first_clone_prompt_ms,
                first_decode_postprocess_ms=first_decode_postprocess_ms,
                first_postprocess_ms=first_postprocess_ms,
                first_decode_only_ms=first_decode_only_ms,
                first_cleanup_ms=first_cleanup_ms,
                first_pcm_encode_ms=first_pcm_encode_ms,
                first_prepare_inference_calls=first_prepare_inference_calls,
                first_batch_size=first_batch_size,
                first_max_condition_len=first_max_condition_len,
                first_max_target_tokens=first_max_target_tokens,
                first_max_ref_audio_tokens=first_max_ref_audio_tokens,
                first_attention_mask_mb_estimate=first_attention_mask_mb_estimate,
                first_batch_logits_mb_estimate=first_batch_logits_mb_estimate,
                first_tokens_mb_estimate=first_tokens_mb_estimate,
                first_cuda_allocated_before_mb=first_cuda_allocated_before_mb,
                first_cuda_allocated_after_mb=first_cuda_allocated_after_mb,
                first_cuda_reserved_before_mb=first_cuda_reserved_before_mb,
                first_cuda_reserved_after_mb=first_cuda_reserved_after_mb,
                first_cuda_free_before_mb=first_cuda_free_before_mb,
                first_cuda_free_after_mb=first_cuda_free_after_mb,
                first_cuda_total_mb=first_cuda_total_mb,
                total_ms=total_ms,
            )
            metrics_svc.record_stream_observation(observation)
            logger.warning(
                "stream request_id=%s mode=%s profile_id=%s status=timeout "
                "planned_calls=%d completed_calls=%d emitted_chunks=%d "
                "emitted_bytes=%d ttfa_ms=%s first_clone_prompt_ms=%s "
                "first_decode_postprocess_ms=%s first_cleanup_ms=%s total_ms=%.1f "
                "timed out on '%s...'",
                request_id,
                base_req.mode,
                profile_id,
                len(sentences),
                completed_synthesis_calls,
                emitted_audio_chunks,
                emitted_bytes,
                _fmt_ms(ttfa_ms),
                _fmt_ms(first_clone_prompt_ms),
                _fmt_ms(first_decode_postprocess_ms),
                _fmt_ms(first_cleanup_ms),
                total_ms,
                sentence[:50],
            )
            return
        except Exception:
            total_ms = (time.monotonic() - stream_started) * 1000
            metrics_svc.record_error()
            observation = _build_stream_observation(
                request_id=request_id,
                mode=base_req.mode,
                profile_id=profile_id,
                input_chars=len(text),
                planned_synthesis_calls=len(sentences),
                first_chunk_chars=first_chunk_chars,
                completed_synthesis_calls=completed_synthesis_calls,
                emitted_audio_chunks=emitted_audio_chunks,
                emitted_bytes=emitted_bytes,
                status="error",
                sentence_split_ms=sentence_split_ms,
                ttfa_ms=ttfa_ms,
                first_synthesis_ms=first_synthesis_ms,
                first_clone_prompt_ms=first_clone_prompt_ms,
                first_decode_postprocess_ms=first_decode_postprocess_ms,
                first_postprocess_ms=first_postprocess_ms,
                first_decode_only_ms=first_decode_only_ms,
                first_cleanup_ms=first_cleanup_ms,
                first_pcm_encode_ms=first_pcm_encode_ms,
                first_prepare_inference_calls=first_prepare_inference_calls,
                first_batch_size=first_batch_size,
                first_max_condition_len=first_max_condition_len,
                first_max_target_tokens=first_max_target_tokens,
                first_max_ref_audio_tokens=first_max_ref_audio_tokens,
                first_attention_mask_mb_estimate=first_attention_mask_mb_estimate,
                first_batch_logits_mb_estimate=first_batch_logits_mb_estimate,
                first_tokens_mb_estimate=first_tokens_mb_estimate,
                first_cuda_allocated_before_mb=first_cuda_allocated_before_mb,
                first_cuda_allocated_after_mb=first_cuda_allocated_after_mb,
                first_cuda_reserved_before_mb=first_cuda_reserved_before_mb,
                first_cuda_reserved_after_mb=first_cuda_reserved_after_mb,
                first_cuda_free_before_mb=first_cuda_free_before_mb,
                first_cuda_free_after_mb=first_cuda_free_after_mb,
                first_cuda_total_mb=first_cuda_total_mb,
                total_ms=total_ms,
            )
            metrics_svc.record_stream_observation(observation)
            logger.exception(
                "stream request_id=%s mode=%s profile_id=%s status=error "
                "planned_calls=%d completed_calls=%d emitted_chunks=%d "
                "emitted_bytes=%d ttfa_ms=%s first_clone_prompt_ms=%s "
                "first_decode_postprocess_ms=%s first_cleanup_ms=%s total_ms=%.1f "
                "failed on '%s...'",
                request_id,
                base_req.mode,
                profile_id,
                len(sentences),
                completed_synthesis_calls,
                emitted_audio_chunks,
                emitted_bytes,
                _fmt_ms(ttfa_ms),
                _fmt_ms(first_clone_prompt_ms),
                _fmt_ms(first_decode_postprocess_ms),
                _fmt_ms(first_cleanup_ms),
                total_ms,
                sentence[:50],
            )
            return

    total_s = time.monotonic() - stream_started
    total_ms = total_s * 1000
    metrics_svc.record_success(total_s)
    observation = _build_stream_observation(
        request_id=request_id,
        mode=base_req.mode,
        profile_id=profile_id,
        input_chars=len(text),
        planned_synthesis_calls=len(sentences),
        first_chunk_chars=first_chunk_chars,
        completed_synthesis_calls=completed_synthesis_calls,
        emitted_audio_chunks=emitted_audio_chunks,
        emitted_bytes=emitted_bytes,
        status="success",
        sentence_split_ms=sentence_split_ms,
        ttfa_ms=ttfa_ms,
        first_synthesis_ms=first_synthesis_ms,
        first_clone_prompt_ms=first_clone_prompt_ms,
        first_decode_postprocess_ms=first_decode_postprocess_ms,
        first_postprocess_ms=first_postprocess_ms,
        first_decode_only_ms=first_decode_only_ms,
        first_cleanup_ms=first_cleanup_ms,
        first_pcm_encode_ms=first_pcm_encode_ms,
        first_prepare_inference_calls=first_prepare_inference_calls,
        first_batch_size=first_batch_size,
        first_max_condition_len=first_max_condition_len,
        first_max_target_tokens=first_max_target_tokens,
        first_max_ref_audio_tokens=first_max_ref_audio_tokens,
        first_attention_mask_mb_estimate=first_attention_mask_mb_estimate,
        first_batch_logits_mb_estimate=first_batch_logits_mb_estimate,
        first_tokens_mb_estimate=first_tokens_mb_estimate,
        first_cuda_allocated_before_mb=first_cuda_allocated_before_mb,
        first_cuda_allocated_after_mb=first_cuda_allocated_after_mb,
        first_cuda_reserved_before_mb=first_cuda_reserved_before_mb,
        first_cuda_reserved_after_mb=first_cuda_reserved_after_mb,
        first_cuda_free_before_mb=first_cuda_free_before_mb,
        first_cuda_free_after_mb=first_cuda_free_after_mb,
        first_cuda_total_mb=first_cuda_total_mb,
        total_ms=total_ms,
    )
    metrics_svc.record_stream_observation(observation)
    logger.info(
        "stream request_id=%s mode=%s profile_id=%s status=success "
        "planned_calls=%d completed_calls=%d emitted_chunks=%d emitted_bytes=%d "
        "split_ms=%.1f ttfa_ms=%s first_synthesis_ms=%s "
        "first_clone_prompt_ms=%s first_decode_postprocess_ms=%s "
        "first_cleanup_ms=%s first_pcm_encode_ms=%s total_ms=%.1f",
        request_id,
        base_req.mode,
        profile_id,
        len(sentences),
        completed_synthesis_calls,
        emitted_audio_chunks,
        emitted_bytes,
        sentence_split_ms,
        _fmt_ms(ttfa_ms),
        _fmt_ms(first_synthesis_ms),
        _fmt_ms(first_clone_prompt_ms),
        _fmt_ms(first_decode_postprocess_ms),
        _fmt_ms(first_cleanup_ms),
        _fmt_ms(first_pcm_encode_ms),
        total_ms,
    )


def _build_stream_observation(**kwargs) -> StreamObservation:
    return StreamObservation(**kwargs)


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


async def _stream_sentences_overlapped(
    text: str,
    base_req: SynthesisRequest,
    inference_svc: InferenceService,
    metrics_svc: MetricsService,
    cfg,
) -> AsyncIterator[bytes]:
    sentences = split_sentences(text, max_chars=cfg.stream_chunk_max_chars)

    if not sentences:
        return

    queue: asyncio.Queue[tuple[str, SynthesisResult | Exception | None]] = asyncio.Queue(maxsize=1)

    async def produce() -> None:
        try:
            for sentence in sentences:
                req = _chunk_request(sentence, base_req)
                try:
                    result = await inference_svc.synthesize(req)
                    metrics_svc.record_success(result.latency_s)
                    await queue.put(("result", result))
                except asyncio.TimeoutError:
                    metrics_svc.record_timeout()
                    logger.warning(f"Streaming chunk timed out: '{sentence[:50]}...'")
                    await queue.put(("stop", None))
                    return
                except Exception as exc:
                    metrics_svc.record_error()
                    logger.exception(f"Streaming chunk failed: '{sentence[:50]}...'")
                    await queue.put(("error", exc))
                    return
            await queue.put(("stop", None))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in streaming producer")
            with suppress(Exception):
                await queue.put(("stop", None))
            raise

    producer = asyncio.create_task(produce())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "result":
                for tensor in payload.tensors:  # type: ignore[union-attr]
                    yield tensor_to_pcm16_bytes(tensor)
            elif kind == "error":
                return
            else:
                return
    finally:
        if not producer.done():
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer
        else:
            with suppress(Exception):
                producer.result()


@router.post("/audio/speech/clone")
async def create_speech_clone(
    request: Request,
    text: str = Form(..., min_length=1, max_length=10_000),
    ref_audio: UploadFile = File(...),
    ref_text: str | None = Form(default=None),
    response_format: ResponseFormat = Form(default="wav"),
    stream: bool = Form(default=False),
    speed: float = Form(default=1.0, ge=0.25, le=4.0),
    num_step: int | None = Form(default=None, ge=1, le=64),
    guidance_scale: float | None = Form(default=None, ge=0.0, le=10.0),
    denoise: bool | None = Form(default=None),
    t_shift: float | None = Form(default=None, ge=0.0, le=2.0),
    position_temperature: float | None = Form(default=None, ge=0.0, le=10.0),
    class_temperature: float | None = Form(default=None, ge=0.0, le=2.0),
    duration: float | None = Form(default=None, ge=0.1, le=60.0),
    language: str | None = Form(
        default=None,
        description="Language code (e.g., 'en', 'vi', 'zh') for multilingual pronunciation",
    ),
    layer_penalty_factor: float | None = Form(default=None, ge=0.0),
    preprocess_prompt: bool | None = Form(default=None),
    postprocess_output: bool | None = Form(default=None),
    audio_chunk_duration: float | None = Form(default=None, gt=0.0),
    audio_chunk_threshold: float | None = Form(default=None, gt=0.0),
    request_timeout_s: int | None = Form(default=None, ge=1, le=600),
    inference_svc: InferenceService = Depends(_get_inference),
    metrics_svc: MetricsService = Depends(_get_metrics),
    cfg=Depends(_get_cfg),
):
    """One-shot voice cloning. Upload reference audio + text to synthesize."""
    # Fail-fast: reject oversized uploads before reading body
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            cl_bytes = int(content_length)
            if cl_bytes > cfg.max_ref_audio_bytes:
                cl_mb = cl_bytes / 1024 / 1024
                limit_mb = cfg.max_ref_audio_bytes / 1024 / 1024
                logger.warning(
                    f"Rejected upload: Content-Length {cl_mb:.1f}MB > limit {limit_mb:.0f}MB"
                )
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Upload too large: {cl_mb:.1f}MB exceeds limit of {limit_mb:.0f}MB",
                )
        except ValueError:
            pass  # Invalid Content-Length header — let body validation handle it

    from ..utils.audio import read_upload_bounded, validate_audio_bytes

    raw = await ref_audio.read()
    try:
        audio_bytes = read_upload_bounded(raw, cfg.max_ref_audio_bytes)
        validate_audio_bytes(audio_bytes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

    def build_request(tmp_path: str) -> SynthesisRequest:
        return SynthesisRequest(
            text=text,
            mode="clone",
            ref_audio_path=tmp_path,
            ref_text=ref_text,
            speed=speed,
            num_step=num_step,
            guidance_scale=guidance_scale,
            denoise=denoise,
            t_shift=t_shift,
            position_temperature=position_temperature,
            class_temperature=class_temperature,
            duration=duration,
            language=language,
            layer_penalty_factor=layer_penalty_factor,
            preprocess_prompt=preprocess_prompt,
            postprocess_output=postprocess_output,
            audio_chunk_duration=audio_chunk_duration,
            audio_chunk_threshold=audio_chunk_threshold,
        )

    if stream or cfg.stream:
        if response_format != "pcm":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Streaming only supports response_format='pcm', got '{response_format}'"
                ),
            )

        async def clone_stream() -> AsyncIterator[bytes]:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = str(Path(tmpdir) / "ref_audio.wav")
                Path(tmp_path).write_bytes(audio_bytes)
                req = build_request(tmp_path)
                stream_iter = (
                    _stream_sentences_overlapped(text, req, inference_svc, metrics_svc, cfg)
                    if cfg.stream_overlap
                    else _stream_sentences(
                        text,
                        req,
                        inference_svc,
                        metrics_svc,
                        cfg,
                        uuid.uuid4().hex[:12],
                        None,
                    )
                )
                async for chunk in stream_iter:
                    yield chunk

        return _pcm_stream_response(clone_stream())

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = str(Path(tmpdir) / "ref_audio.wav")
        Path(tmp_path).write_bytes(audio_bytes)
        req = build_request(tmp_path)
        timeout_s = _effective_timeout_s(request_timeout_s, cfg)

        try:
            if request_timeout_s is not None:
                result = await inference_svc.synthesize(req, timeout_override=request_timeout_s)
            else:
                result = await inference_svc.synthesize(req)
            metrics_svc.record_success(result.latency_s)
        except asyncio.TimeoutError:
            metrics_svc.record_timeout()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Synthesis timed out after {timeout_s}s",
            )
        except Exception as e:
            metrics_svc.record_error()
            logger.exception("Clone synthesis failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Synthesis failed: {e}",
            )

        try:
            audio_output, media_type = tensors_to_formatted_bytes(result.tensors, response_format)
        except RuntimeError as e:
            logger.warning(f"Format conversion failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=f"Audio format '{response_format}' not available: {e}",
            )

        return Response(
            content=audio_output,
            media_type=media_type,
            headers={
                "X-Audio-Duration-S": str(round(result.duration_s, 3)),
                "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
            },
        )
