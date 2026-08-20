"""
Runs model.generate() in a thread pool with concurrency limiting and
post-request memory cleanup.

DESIGN NOTE — upstream isolation:
  All kwargs construction for model.generate() is centralised in
  OmniVoiceAdapter._build_kwargs(). When OmniVoice adds / renames params,
  only that one method changes — not SynthesisRequest, not the router.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import torch

from ..config import Settings
from .model import ModelService, ModelTimingBreakdown

logger = logging.getLogger(__name__)


@dataclass
class SynthesisRequest:
    text: str
    mode: str  # "auto" | "design" | "clone"
    instruct: str | None = None  # for mode="design"
    ref_audio_path: str | None = None  # tmp path, for mode="clone"
    ref_text: str | None = None  # for mode="clone", optional
    profile_id: str | None = None  # for stored clone profiles
    voice_clone_prompt: object | None = None  # cached upstream prompt object
    speed: float = 1.0
    num_step: int | None = None  # None → use server default
    # Advanced passthrough — None means "use upstream default"
    guidance_scale: float | None = None
    denoise: bool | None = None
    t_shift: float | None = None
    position_temperature: float | None = None
    class_temperature: float | None = None
    duration: float | None = None  # Fixed output duration in seconds
    language: str | None = None  # Optional language code for multilingual pronunciation
    layer_penalty_factor: float | None = None
    preprocess_prompt: bool | None = None
    postprocess_output: bool | None = None
    audio_chunk_duration: float | None = None
    audio_chunk_threshold: float | None = None


@dataclass
class SynthesisResult:
    tensors: list  # list[torch.Tensor], each (1, T)
    duration_s: float
    latency_s: float
    breakdown: SynthesisTimingBreakdown | None = None


@dataclass
class SynthesisTimingBreakdown:
    clone_prompt_ms: float = 0.0
    clone_prompt_calls: int = 0
    decode_postprocess_ms: float = 0.0
    decode_postprocess_calls: int = 0
    postprocess_ms: float = 0.0
    postprocess_calls: int = 0
    cleanup_ms: float = 0.0
    prepare_inference_calls: int = 0
    batch_size: int = 0
    max_condition_len: int = 0
    max_target_tokens: int = 0
    max_ref_audio_tokens: int = 0
    attention_mask_mb_estimate: float = 0.0
    batch_logits_mb_estimate: float = 0.0
    tokens_mb_estimate: float = 0.0
    cuda_allocated_before_mb: float = 0.0
    cuda_allocated_after_mb: float = 0.0
    cuda_reserved_before_mb: float = 0.0
    cuda_reserved_after_mb: float = 0.0
    cuda_free_before_mb: float = 0.0
    cuda_free_after_mb: float = 0.0
    cuda_total_mb: float = 0.0

    @property
    def decode_only_ms(self) -> float:
        return max(0.0, self.decode_postprocess_ms - self.postprocess_ms)

    @classmethod
    def from_model_timing(
        cls,
        model_timing: ModelTimingBreakdown,
        cleanup_ms: float,
        cuda_before: dict[str, float],
        cuda_after: dict[str, float],
    ) -> SynthesisTimingBreakdown:
        return cls(
            clone_prompt_ms=model_timing.clone_prompt_ms,
            clone_prompt_calls=model_timing.clone_prompt_calls,
            decode_postprocess_ms=model_timing.decode_postprocess_ms,
            decode_postprocess_calls=model_timing.decode_postprocess_calls,
            postprocess_ms=model_timing.postprocess_ms,
            postprocess_calls=model_timing.postprocess_calls,
            cleanup_ms=cleanup_ms,
            prepare_inference_calls=model_timing.prepare_inference_calls,
            batch_size=model_timing.batch_size,
            max_condition_len=model_timing.max_condition_len,
            max_target_tokens=model_timing.max_target_tokens,
            max_ref_audio_tokens=model_timing.max_ref_audio_tokens,
            attention_mask_mb_estimate=model_timing.attention_mask_mb_estimate,
            batch_logits_mb_estimate=model_timing.batch_logits_mb_estimate,
            tokens_mb_estimate=model_timing.tokens_mb_estimate,
            cuda_allocated_before_mb=cuda_before["allocated_mb"],
            cuda_allocated_after_mb=cuda_after["allocated_mb"],
            cuda_reserved_before_mb=cuda_before["reserved_mb"],
            cuda_reserved_after_mb=cuda_after["reserved_mb"],
            cuda_free_before_mb=cuda_before["free_mb"],
            cuda_free_after_mb=cuda_after["free_mb"],
            cuda_total_mb=cuda_after["total_mb"] or cuda_before["total_mb"],
        )


class OmniVoiceAdapter:
    """
    Thin adapter that translates SynthesisRequest → model.generate() kwargs.

    WHY THIS EXISTS:
    OmniVoice.generate() accepts ~10 parameters (num_step, speed, instruct,
    ref_audio, ref_text, guidance_scale, denoise, duration, …). As upstream
    adds / renames parameters, only this class needs to change — not the
    request schema, not the router, not the tests.

    This is the single seam between omnivoice-server and the upstream library.
    """

    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg

    def build_kwargs(self, req: SynthesisRequest, model) -> dict:
        """Return kwargs dict ready to pass to model.generate()."""
        logger.debug(
            f"[TRACE] OmniVoiceAdapter.build_kwargs called: mode={req.mode!r}, "
            f"text={req.text[:50]!r}..., instruct={req.instruct!r}, "
            f"ref_audio_path={req.ref_audio_path!r}, ref_text={req.ref_text!r}, "
            f"speed={req.speed}, num_step={req.num_step}, guidance_scale={req.guidance_scale}, "
            f"denoise={req.denoise}, language={req.language}"
        )
        num_step = req.num_step or self._cfg.num_step
        guidance_scale = (
            req.guidance_scale if req.guidance_scale is not None else self._cfg.guidance_scale
        )
        denoise = req.denoise if req.denoise is not None else self._cfg.denoise
        t_shift = req.t_shift if req.t_shift is not None else self._cfg.t_shift
        position_temperature = (
            req.position_temperature
            if req.position_temperature is not None
            else self._cfg.position_temperature
        )
        class_temperature = (
            req.class_temperature
            if req.class_temperature is not None
            else self._cfg.class_temperature
        )

        kwargs: dict = {
            "text": req.text,
            "num_step": num_step,
            "speed": req.speed,
            "guidance_scale": guidance_scale,
            "denoise": denoise,
            "t_shift": t_shift,
            "position_temperature": position_temperature,
            "class_temperature": class_temperature,
        }

        # Add optional duration parameter if provided
        if req.duration is not None:
            kwargs["duration"] = req.duration

        if req.language is not None:
            kwargs["language"] = req.language

        if req.layer_penalty_factor is not None:
            kwargs["layer_penalty_factor"] = req.layer_penalty_factor
        if req.preprocess_prompt is not None:
            kwargs["preprocess_prompt"] = req.preprocess_prompt
        if req.postprocess_output is not None:
            kwargs["postprocess_output"] = req.postprocess_output
        if req.audio_chunk_duration is not None:
            kwargs["audio_chunk_duration"] = req.audio_chunk_duration
        if req.audio_chunk_threshold is not None:
            kwargs["audio_chunk_threshold"] = req.audio_chunk_threshold

        if req.mode == "design" and req.instruct:
            kwargs["instruct"] = req.instruct
        elif req.mode == "clone":
            if req.voice_clone_prompt is not None:
                kwargs["voice_clone_prompt"] = req.voice_clone_prompt
            elif req.ref_audio_path:
                kwargs["ref_audio"] = req.ref_audio_path
                if req.ref_text:
                    kwargs["ref_text"] = req.ref_text

        logger.debug(f"[TRACE] Final kwargs keys: {list(kwargs.keys())}")
        return kwargs

    def call(self, req: SynthesisRequest, model) -> list[torch.Tensor]:
        """Call model.generate() and return raw tensors."""
        kwargs = self.build_kwargs(req, model)
        try:
            return model.generate(**kwargs)
        except TypeError as exc:
            # Upstream renamed or removed a param — try graceful fallback
            # by stripping unknown kwargs one-by-one.
            logger.warning(
                f"model.generate() raised TypeError: {exc}. "
                "Attempting fallback with minimal kwargs."
            )
            minimal = {
                "text": kwargs["text"],
                "num_step": kwargs.get("num_step", 16),
            }
            if "instruct" in kwargs:
                minimal["instruct"] = kwargs["instruct"]
            if "voice_clone_prompt" in kwargs:
                minimal["voice_clone_prompt"] = kwargs["voice_clone_prompt"]
            if "ref_audio" in kwargs:
                minimal["ref_audio"] = kwargs["ref_audio"]
            if "ref_text" in kwargs:
                minimal["ref_text"] = kwargs["ref_text"]
            return model.generate(**minimal)


class InferenceService:
    def __init__(
        self,
        model_svc: ModelService,
        executor: ThreadPoolExecutor,
        cfg: Settings,
    ) -> None:
        self._model_svc = model_svc
        self._executor = executor
        self._cfg = cfg
        # FlashInfer keeps per-model packed-attention context and optional CUDA
        # graphs; serialize its opt-in path to avoid cross-request context
        # corruption. Standard inference retains configured concurrency.
        concurrency = (
            1 if cfg.flashinfer_mode and cfg.device == "cuda" else cfg.max_concurrent
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self._adapter = OmniVoiceAdapter(cfg)
        self._cleanup_counter = 0
        self._cleanup_lock = threading.Lock()

    async def synthesize(
        self,
        req: SynthesisRequest,
        timeout_override: int | None = None,
    ) -> SynthesisResult:
        """
        Run synthesis in thread pool.
        Blocks at semaphore if MAX_CONCURRENT already running.
        Raises asyncio.TimeoutError if exceeds request_timeout_s.
        """
        loop = asyncio.get_running_loop()

        timeout_s = timeout_override or self._cfg.request_timeout_s

        async with self._semaphore:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    self._run_sync,
                    req,
                ),
                timeout=timeout_s,
            )

        return result

    async def prepare_clone_request(self, req: SynthesisRequest) -> SynthesisRequest:
        """Prepare clone conditioning once for a multi-chunk stream."""
        if (
            req.mode != "clone"
            or not req.ref_audio_path
            or req.voice_clone_prompt is not None
        ):
            return req

        loop = asyncio.get_running_loop()
        async with self._semaphore:
            if req.profile_id:
                prompt = await loop.run_in_executor(
                    self._executor,
                    self._model_svc.get_or_create_voice_clone_prompt,
                    req.profile_id,
                    req.ref_audio_path,
                    req.ref_text,
                )
            else:
                prompt = await loop.run_in_executor(
                    self._executor,
                    self._model_svc.create_voice_clone_prompt,
                    req.ref_audio_path,
                    req.ref_text,
                    req.preprocess_prompt,
                )
        return replace(req, voice_clone_prompt=prompt)

    def _run_sync(self, req: SynthesisRequest) -> SynthesisResult:
        """Blocking inference. Runs in thread pool thread."""
        t0 = time.monotonic()
        model = self._model_svc.model
        self._model_svc.begin_timing_capture()
        cleanup_ms = 0.0
        model_timing = ModelTimingBreakdown()
        prepared_req = req
        cuda_before = _capture_cuda_memory(self._cfg.device)
        cuda_after = cuda_before

        try:
            if (
                req.mode == "clone"
                and req.profile_id
                and req.ref_audio_path
                and req.voice_clone_prompt is None
            ):
                prompt = self._model_svc.get_or_create_voice_clone_prompt(
                    profile_id=req.profile_id,
                    ref_audio_path=req.ref_audio_path,
                    ref_text=req.ref_text,
                )
                prepared_req = replace(req, voice_clone_prompt=prompt)
            elif (
                req.mode == "clone"
                and req.ref_audio_path
                and req.ref_text is None
                and self._cfg.transcriber == "faster-whisper"
            ):
                transcript = self._model_svc.transcribe_reference(req.ref_audio_path)
                if transcript:
                    prepared_req = replace(req, ref_text=transcript)
            tensors = self._adapter.call(prepared_req, model)
            cuda_after = _capture_cuda_memory(self._cfg.device)
        finally:
            if self._should_cleanup():
                cleanup_started = time.monotonic()
                _cleanup_memory(self._cfg.device)
                cleanup_ms = (time.monotonic() - cleanup_started) * 1000
            model_timing = self._model_svc.end_timing_capture()

        duration_s = sum(t.shape[-1] for t in tensors) / 24_000
        latency_s = time.monotonic() - t0

        logger.debug(
            f"Synthesized {duration_s:.2f}s audio in {latency_s:.2f}s "
            f"(RTF={latency_s / duration_s:.3f})"
        )
        return SynthesisResult(
            tensors=tensors,
            duration_s=duration_s,
            latency_s=latency_s,
            breakdown=SynthesisTimingBreakdown.from_model_timing(
                model_timing,
                cleanup_ms,
                cuda_before,
                cuda_after,
            ),
        )

    def _should_cleanup(self) -> bool:
        interval = self._cfg.cleanup_interval
        if interval <= 0:
            return False

        with self._cleanup_lock:
            self._cleanup_counter += 1
            return self._cleanup_counter % interval == 0


def _cleanup_memory(device: str) -> None:
    """Post-inference memory cleanup to mitigate potential Torch memory growth."""
    gc.collect()
    if device == "cuda":
        try:
            torch.cuda.empty_cache()
        except Exception as e:
            logger.debug(f"CUDA cache cleanup failed (non-fatal): {e}")
    elif device == "mps":
        try:
            torch.mps.empty_cache()
        except Exception as e:
            logger.debug(f"MPS cache cleanup failed (non-fatal): {e}")


def _capture_cuda_memory(device: str) -> dict[str, float]:
    snapshot = {
        "allocated_mb": 0.0,
        "reserved_mb": 0.0,
        "free_mb": 0.0,
        "total_mb": 0.0,
    }
    if device != "cuda" or not torch.cuda.is_available():
        return snapshot

    free_bytes, total_bytes = torch.cuda.mem_get_info()
    snapshot["allocated_mb"] = torch.cuda.memory_allocated() / 1024 / 1024
    snapshot["reserved_mb"] = torch.cuda.memory_reserved() / 1024 / 1024
    snapshot["free_mb"] = free_bytes / 1024 / 1024
    snapshot["total_mb"] = total_bytes / 1024 / 1024
    return snapshot
