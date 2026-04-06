"""
Runs model.generate() in a thread pool with concurrency limiting and
post-request memory cleanup.

Supports two modes:
  1. Dynamic batching (default): requests are accumulated by BatchingService
     and dispatched as a single batched model.generate() call.
  2. Legacy single-request mode: each request runs independently in the
     thread pool with semaphore-based concurrency limiting.

DESIGN NOTE — upstream isolation:
  All kwargs construction for model.generate() is centralised in
  OmniVoiceAdapter._build_kwargs(). When OmniVoice adds / renames params,
  only that one method changes — not SynthesisRequest, not the router.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import torch

from ..config import Settings
from .model import ModelService

# Re-export from batching so existing imports (routers, tests) keep working.
from .batching import SynthesisRequest, SynthesisResult  # noqa: F401

if TYPE_CHECKING:
    from .batching import BatchingService

logger = logging.getLogger(__name__)


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

        if req.mode == "design" and req.instruct:
            kwargs["instruct"] = req.instruct
        elif req.mode == "clone" and req.ref_audio_path:
            kwargs["ref_audio"] = req.ref_audio_path
            if req.ref_text:
                kwargs["ref_text"] = req.ref_text

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
    """
    Unified inference entry point.

    When batching is enabled (cfg.batch_enabled), delegates to BatchingService.
    Otherwise falls back to the legacy single-request thread pool path.
    """

    def __init__(
        self,
        model_svc: ModelService,
        executor: ThreadPoolExecutor,
        cfg: Settings,
        batching_svc: BatchingService | None = None,
    ) -> None:
        self._model_svc = model_svc
        self._executor = executor
        self._cfg = cfg
        self._adapter = OmniVoiceAdapter(cfg)
        self._batching_svc = batching_svc
        # Semaphore only used in legacy (non-batched) mode.
        # When batching is active, BatchingService owns its own semaphore.
        self._semaphore = asyncio.Semaphore(cfg.max_concurrent)

    async def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        """
        Run synthesis — batched or single-request depending on config.

        Raises asyncio.TimeoutError if exceeds request_timeout_s.
        """
        if self._batching_svc is not None:
            return await self._batching_svc.submit(req)

        # Legacy single-request path
        return await self._synthesize_single(req)

    async def _synthesize_single(self, req: SynthesisRequest) -> SynthesisResult:
        """Legacy: run a single request in the thread pool with semaphore."""
        loop = asyncio.get_running_loop()

        async with self._semaphore:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    self._run_sync,
                    req,
                ),
                timeout=self._cfg.request_timeout_s,
            )

        return result

    def _run_sync(self, req: SynthesisRequest) -> SynthesisResult:
        """Blocking inference. Runs in thread pool thread."""
        t0 = time.monotonic()
        model = self._model_svc.model

        try:
            tensors = self._adapter.call(req, model)
        finally:
            _cleanup_memory(self._cfg.device)

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
