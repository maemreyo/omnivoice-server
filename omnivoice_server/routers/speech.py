"""
/v1/audio/speech        - OpenAI-compatible TTS (instructions-driven design)
/v1/audio/speech/clone  - One-shot voice cloning (multipart upload)
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..services.inference import InferenceService, SynthesisRequest
from ..services.metrics import MetricsService
from ..services.profiles import ProfileService
from ..utils.audio import tensor_to_pcm16_bytes, tensors_to_wav_bytes
from ..utils.text import split_sentences
from ..voice_presets import DEFAULT_DESIGN_INSTRUCTIONS, OPENAI_VOICE_PRESETS

logger = logging.getLogger(__name__)
router = APIRouter()


class SpeechRequest(BaseModel):
    """OpenAI TTS API compatible request body."""

    model: str = Field(default="omnivoice")
    input: str = Field(..., min_length=1, max_length=10_000)
    voice: str = Field(default="auto")
    speaker: str | None = Field(default=None)
    instructions: str | None = Field(default=None)
    response_format: Literal["wav", "pcm"] = Field(default="wav")
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    stream: bool = Field(default=False)
    num_step: int | None = Field(default=None, ge=1, le=64)
    guidance_scale: float | None = Field(default=None, ge=0.0, le=10.0)
    denoise: bool | None = Field(default=None)
    t_shift: float | None = Field(default=None, ge=0.0, le=2.0)
    position_temperature: float | None = Field(default=None, ge=0.0, le=10.0)
    class_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    duration: float | None = Field(default=None, ge=0.1, le=60.0)

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


def _resolve_synthesis_mode(
    body: SpeechRequest,
    profile_svc: ProfileService,
) -> tuple[str, str | None, str | None, str | None]:
    """Resolve synthesis mode for /v1/audio/speech."""
    del profile_svc
    instructions = body.instructions.strip() if body.instructions else None
    speaker = body.speaker.strip().lower() if body.speaker else None
    voice = body.voice.strip().lower() if body.voice else None

    if instructions:
        return "design", instructions, None, None

    if speaker and speaker in OPENAI_VOICE_PRESETS:
        return "design", OPENAI_VOICE_PRESETS[speaker], None, None

    if voice and voice in OPENAI_VOICE_PRESETS:
        return "design", OPENAI_VOICE_PRESETS[voice], None, None

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
    )

    if body.stream:
        return StreamingResponse(
            _stream_sentences(body.input, req, inference_svc, metrics_svc, cfg),
            media_type="audio/pcm",
            headers={
                "X-Audio-Sample-Rate": "24000",
                "X-Audio-Channels": "1",
                "X-Audio-Bit-Depth": "16",
                "X-Audio-Format": "pcm-int16-le",
            },
        )

    try:
        result = await inference_svc.synthesize(req)
        metrics_svc.record_success(result.latency_s)
    except asyncio.TimeoutError:
        metrics_svc.record_timeout()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Synthesis timed out after {cfg.request_timeout_s}s",
        )
    except Exception as e:
        metrics_svc.record_error()
        logger.exception("Synthesis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {e}",
        )

    if body.response_format == "pcm":
        audio_bytes = b"".join(tensor_to_pcm16_bytes(t) for t in result.tensors)
        media_type = "audio/pcm"
    else:
        audio_bytes = tensors_to_wav_bytes(result.tensors)
        media_type = "audio/wav"

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "X-Audio-Duration-S": str(round(result.duration_s, 3)),
            "X-Synthesis-Latency-S": str(round(result.latency_s, 3)),
        },
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
        req = SynthesisRequest(
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
        )
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
        )
        try:
            result = await inference_svc.synthesize(req)
            metrics_svc.record_success(result.latency_s)
        except asyncio.TimeoutError:
            metrics_svc.record_timeout()
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Synthesis timed out after {cfg.request_timeout_s}s",
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
