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
from dataclasses import dataclass

import torch

from ..config import Settings
from ..utils.audio import is_degenerate_audio
from .model import ModelService

logger = logging.getLogger(__name__)


@dataclass
class SynthesisRequest:
    text: str
    mode: str  # "auto" | "design" | "clone"
    instruct: str | None = None  # for mode="design"
    ref_audio_path: str | None = None  # tmp path, for mode="clone"
    ref_text: str | None = None  # for mode="clone", optional
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
    seed: int | None = None  # None → server default, which may itself be None


@dataclass
class SynthesisResult:
    tensors: list  # list[torch.Tensor], each (1, T)
    duration_s: float
    latency_s: float
    no_speech_detected: bool = False  # Output looks like a drone, not speech


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
            logger.info(f"[TRACE] DESIGN mode kwargs prepared: instruct={req.instruct!r}")
        elif req.mode == "clone" and req.ref_audio_path:
            kwargs["ref_audio"] = req.ref_audio_path
            if req.ref_text:
                kwargs["ref_text"] = req.ref_text
            logger.info(
                "[TRACE] CLONE mode kwargs prepared: ref_audio=%s, ref_text=%r",
                req.ref_audio_path,
                req.ref_text,
            )
        else:
            logger.warning(f"[TRACE] Unknown/unsupported mode: {req.mode!r}")

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
        self._semaphore = asyncio.Semaphore(cfg.max_concurrent)
        self._adapter = OmniVoiceAdapter(cfg)
        # torch's RNG is process-global, so two seeded generations running in
        # different pool threads would consume each other's random state.
        self._seed_lock = threading.Lock()
        self._seed_concurrency_warned = False

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

    def _run_sync(self, req: SynthesisRequest) -> SynthesisResult:
        """Blocking inference. Runs in thread pool thread."""
        t0 = time.monotonic()
        model = self._model_svc.model
        seed = req.seed if req.seed is not None else self._cfg.seed

        try:
            tensors = self._generate(req, model, seed)
        finally:
            _cleanup_memory(self._cfg.device)

        no_speech = self._looks_like_no_speech(tensors)
        if no_speech:
            logger.warning(
                "Generation contains no detectable speech — a steady low-frequency "
                "drone rather than a voice. This happens when several non-verbal "
                "tags share one short utterance; no generation parameter is known "
                "to recover it. Try spreading tags across sentences. Text: %r",
                req.text[:120],
            )

        duration_s = sum(t.shape[-1] for t in tensors) / 24_000
        latency_s = time.monotonic() - t0

        # An f-string argument is built whether or not debug logging is on, so a
        # zero-length generation used to raise ZeroDivisionError here and surface
        # as a 500 — turning empty audio into a crash on the logging line.
        rtf = f"{latency_s / duration_s:.3f}" if duration_s > 0 else "n/a"
        logger.debug("Synthesized %.2fs audio in %.2fs (RTF=%s)", duration_s, latency_s, rtf)

        if duration_s == 0:
            logger.warning("Generation returned no audio for text: %r", req.text[:80])
        return SynthesisResult(
            tensors=tensors,
            duration_s=duration_s,
            latency_s=latency_s,
            no_speech_detected=no_speech,
        )

    def _generate(self, req: SynthesisRequest, model, seed: int | None) -> list[torch.Tensor]:
        """Run one generation, seeding the global RNG first when asked to."""
        if seed is None:
            return self._adapter.call(req, model)

        if self._cfg.max_concurrent > 1 and not self._seed_concurrency_warned:
            self._seed_concurrency_warned = True
            logger.warning(
                "seed is set but max_concurrent=%d. Seeded requests are serialised "
                "against each other, but an unseeded request generating at the same "
                "time still advances the shared RNG. Use --max-concurrent 1 for "
                "bit-exact reproducibility.",
                self._cfg.max_concurrent,
            )

        with self._seed_lock:
            torch.manual_seed(seed)
            return self._adapter.call(req, model)

    def _looks_like_no_speech(self, tensors: list) -> bool:
        """
        Whether a generation came back as a drone rather than a voice.

        Reported, not retried. Measured against the real model, no parameter
        combination recovers the case this detects — including
        position_temperature=0, which an earlier version of this code retried
        into. Re-rolling would double the latency and return the same thing.
        """
        if not self._cfg.detect_no_speech:
            return False

        return is_degenerate_audio(
            tensors,
            min_speech_ratio=self._cfg.min_speech_ratio,
        )


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
