"""
/v1/audio/speech        - OpenAI-compatible TTS (instructions-driven design)
/v1/audio/speech/clone  - One-shot voice cloning (multipart upload)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..services.inference import InferenceService, SynthesisRequest, SynthesisResult
from ..services.metrics import MetricsService
from ..services.profiles import ProfileNotFoundError, ProfileService
from ..utils.audio import (
    ResponseFormat,
    tensor_to_pcm16_bytes,
    tensors_to_formatted_bytes,
    tensors_to_wav_bytes,
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

    req = SynthesisRequest(
        text=body.input,
        mode=mode,
        instruct=instruct,
        ref_audio_path=ref_audio_path,
        ref_text=ref_text,
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
        # Streaming only supports PCM
        # (WAV streaming requires implementation of streaming RIFF headers)
        if body.response_format != "pcm":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Streaming only supports response_format='pcm', got '{body.response_format}'"
                ),
            )
        stream_iter = (
            _stream_sentences_overlapped(body.input, req, inference_svc, metrics_svc, cfg)
            if cfg.stream_overlap
            else _stream_sentences(body.input, req, inference_svc, metrics_svc, cfg)
        )
        return StreamingResponse(
            stream_iter,
            media_type="audio/pcm",
            headers={
                "X-Audio-Sample-Rate": "24000",
                "X-Audio-Channels": "1",
                "X-Audio-Bit-Depth": "16",
                "X-Audio-Format": "pcm-int16-le",
            },
        )

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
) -> AsyncIterator[bytes]:
    """Sentence-level streaming generator."""
    sentences = split_sentences(text, max_chars=cfg.stream_chunk_max_chars)

    if not sentences:
        return

    for sentence in sentences:
        req = _chunk_request(sentence, base_req)
        try:
            result = await inference_svc.synthesize(req)
            metrics_svc.record_success(result.latency_s)
            for tensor in result.tensors:
                yield tensor_to_pcm16_bytes(tensor)
        except asyncio.TimeoutError:
            metrics_svc.record_timeout()
            logger.warning(f"Streaming chunk timed out: '{sentence[:50]}...'")
            return
        except Exception:
            metrics_svc.record_error()
            logger.exception(f"Streaming chunk failed: '{sentence[:50]}...'")
            return


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

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = str(Path(tmpdir) / "ref_audio.wav")
        Path(tmp_path).write_bytes(audio_bytes)

        req = SynthesisRequest(
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

        return Response(
            content=tensors_to_wav_bytes(result.tensors),
            media_type="audio/wav",
            headers={
                "X-Audio-Duration-S": str(round(result.duration_s, 3)),
                "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
            },
        )
