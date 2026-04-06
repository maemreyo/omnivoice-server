"""
Dynamic batching service for OmniVoice inference.

Accumulates incoming synthesis requests over a short time window, then
dispatches them as a single batched model.generate() call. This exploits
the upstream OmniVoice API's native batch support (lists of text, ref_audio,
etc.) to improve GPU utilisation and throughput under concurrent load.

DESIGN:
  - Requests arrive via submit() and get an asyncio.Future back.
  - A background loop collects requests into a batch until either:
      (a) batch_max_size is reached, or
      (b) batch_timeout_ms elapses since the first request in the batch.
  - The batch is then dispatched to a single model.generate() call in
    the thread pool executor.
  - Each request's Future is resolved with its individual result (or exception).
  - Requests with incompatible generation parameters are grouped into
    separate "parameter groups" and dispatched independently.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import torch

from ..config import Settings
from .model import ModelService

logger = logging.getLogger(__name__)


@dataclass
class SynthesisRequest:
    text: str
    mode: str  # "auto" | "design" | "clone"
    instruct: str | None = None
    ref_audio_path: str | None = None
    ref_text: str | None = None
    speed: float = 1.0
    num_step: int | None = None
    guidance_scale: float | None = None
    denoise: bool | None = None
    t_shift: float | None = None
    position_temperature: float | None = None
    class_temperature: float | None = None
    duration: float | None = None


@dataclass
class SynthesisResult:
    tensors: list  # list[torch.Tensor], each (1, T)
    duration_s: float
    latency_s: float


@dataclass
class _PendingRequest:
    """A request waiting to be batched."""
    req: SynthesisRequest
    future: asyncio.Future
    submitted_at: float = field(default_factory=time.monotonic)


def _gen_param_key(req: SynthesisRequest, cfg: Settings) -> tuple:
    """
    Return a hashable key representing the generation parameters.

    Requests can only be batched together if they share the same generation
    config (num_step, guidance_scale, etc.). Text, voice mode, ref_audio,
    instruct, speed, and duration vary per-item and are handled natively
    by the upstream batch API.
    """
    return (
        req.num_step or cfg.num_step,
        req.guidance_scale if req.guidance_scale is not None else cfg.guidance_scale,
        req.denoise if req.denoise is not None else cfg.denoise,
        req.t_shift if req.t_shift is not None else cfg.t_shift,
        req.position_temperature if req.position_temperature is not None else cfg.position_temperature,
        req.class_temperature if req.class_temperature is not None else cfg.class_temperature,
    )


class BatchingService:
    """
    Accumulates requests and dispatches them as batched model.generate() calls.

    Thread-safety: all mutation of _pending happens on the asyncio event loop.
    The blocking model.generate() runs in the thread pool executor.
    """

    def __init__(
        self,
        model_svc: ModelService,
        executor: ThreadPoolExecutor,
        cfg: Settings,
    ) -> None:
        self._model_svc = model_svc
        self._executor = executor
        self._cfg = cfg
        self._pending: dict[tuple, list[_PendingRequest]] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._notify = asyncio.Event()
        self._running = False
        # Limit concurrent batch dispatches to the executor thread count.
        # Without this, multiple param groups dispatching simultaneously
        # could queue unboundedly in the executor, defeating backpressure.
        self._batch_semaphore = asyncio.Semaphore(cfg.max_concurrent)

    async def start(self) -> None:
        """Start the background dispatch loop."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info(
            f"BatchingService started (max_size={self._cfg.batch_max_size}, "
            f"timeout_ms={self._cfg.batch_timeout_ms})"
        )

    async def stop(self) -> None:
        """Stop the dispatch loop and cancel pending requests."""
        self._running = False
        self._notify.set()
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        # Fail any remaining pending requests
        for group in self._pending.values():
            for pr in group:
                if not pr.future.done():
                    pr.future.set_exception(
                        RuntimeError("BatchingService shutting down")
                    )
        self._pending.clear()

    async def submit(self, req: SynthesisRequest) -> SynthesisResult:
        """
        Submit a request for batched inference.
        Returns a SynthesisResult when the batch completes.
        Raises asyncio.TimeoutError if request_timeout_s is exceeded.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[SynthesisResult] = loop.create_future()

        key = _gen_param_key(req, self._cfg)
        if key not in self._pending:
            self._pending[key] = []
        self._pending[key].append(_PendingRequest(req=req, future=future))

        # Wake the dispatch loop
        self._notify.set()

        # If this group is already at max size, dispatch immediately
        if len(self._pending[key]) >= self._cfg.batch_max_size:
            self._notify.set()

        return await asyncio.wait_for(
            future,
            timeout=self._cfg.request_timeout_s,
        )

    async def _dispatch_loop(self) -> None:
        """Background loop that collects and dispatches batches."""
        timeout_s = self._cfg.batch_timeout_ms / 1000.0

        while self._running:
            # Wait for at least one request
            self._notify.clear()
            try:
                await asyncio.wait_for(
                    self._notify.wait(),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                pass

            if not self._running:
                break

            # Check each parameter group for ready batches
            now = time.monotonic()
            groups_to_dispatch: list[tuple[tuple, list[_PendingRequest]]] = []

            for key, pending in list(self._pending.items()):
                if not pending:
                    continue

                oldest = pending[0].submitted_at
                batch_full = len(pending) >= self._cfg.batch_max_size
                timed_out = (now - oldest) >= timeout_s

                if batch_full or timed_out:
                    # Take up to batch_max_size
                    batch = pending[:self._cfg.batch_max_size]
                    self._pending[key] = pending[self._cfg.batch_max_size:]
                    if not self._pending[key]:
                        del self._pending[key]
                    groups_to_dispatch.append((key, batch))

            # Dispatch all ready groups concurrently
            if groups_to_dispatch:
                tasks = [
                    self._dispatch_batch(key, batch)
                    for key, batch in groups_to_dispatch
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

            # If there are still pending requests, loop quickly
            if self._pending:
                self._notify.set()

    async def _dispatch_batch(
        self,
        param_key: tuple,
        batch: list[_PendingRequest],
    ) -> None:
        """Dispatch a single batch to model.generate() in the thread pool."""
        loop = asyncio.get_running_loop()
        batch_size = len(batch)

        logger.debug(
            f"Dispatching batch of {batch_size} requests "
            f"(params={param_key})"
        )

        async with self._batch_semaphore:
            try:
                results = await loop.run_in_executor(
                    self._executor,
                    self._run_batch_sync,
                    batch,
                    param_key,
                )
                # Distribute results to individual futures
                for pr, result in zip(batch, results):
                    if not pr.future.done():
                        pr.future.set_result(result)
            except Exception as exc:
                logger.exception(f"Batch inference failed ({batch_size} requests)")
                for pr in batch:
                    if not pr.future.done():
                        pr.future.set_exception(exc)

    def _run_batch_sync(
        self,
        batch: list[_PendingRequest],
        param_key: tuple,
    ) -> list[SynthesisResult]:
        """
        Blocking batched inference. Runs in thread pool.

        Builds lists of per-item parameters and calls model.generate() once
        with the upstream batch API.
        """
        t0 = time.monotonic()
        model = self._model_svc.model
        n = len(batch)

        # Unpack the shared generation params from the key
        num_step, guidance_scale, denoise, t_shift, pos_temp, cls_temp = param_key

        # Build per-item lists
        texts: list[str] = []
        instructs: list[str | None] = []
        ref_audios: list[str | None] = []
        ref_texts: list[str | None] = []
        speeds: list[float] = []
        durations: list[float | None] = []

        for pr in batch:
            req = pr.req
            texts.append(req.text)
            speeds.append(req.speed)
            durations.append(req.duration)

            if req.mode == "design" and req.instruct:
                instructs.append(req.instruct)
                ref_audios.append(None)
                ref_texts.append(None)
            elif req.mode == "clone" and req.ref_audio_path:
                instructs.append(None)
                ref_audios.append(req.ref_audio_path)
                ref_texts.append(req.ref_text)
            else:
                # auto mode
                instructs.append(None)
                ref_audios.append(None)
                ref_texts.append(None)

        # Build kwargs for model.generate()
        kwargs: dict[str, Any] = {
            "text": texts if n > 1 else texts[0],
            "num_step": num_step,
            "guidance_scale": guidance_scale,
            "denoise": denoise,
            "t_shift": t_shift,
            "position_temperature": pos_temp,
            "class_temperature": cls_temp,
        }

        # Per-item optional params — only pass as lists for batch
        if n > 1:
            if any(d is not None for d in durations):
                kwargs["duration"] = durations
            if any(s != 1.0 for s in speeds):
                kwargs["speed"] = speeds
            # Handle mixed modes in batch
            if any(i is not None for i in instructs):
                kwargs["instruct"] = instructs
            if any(r is not None for r in ref_audios):
                kwargs["ref_audio"] = ref_audios
            if any(r is not None for r in ref_texts):
                kwargs["ref_text"] = ref_texts
        else:
            req = batch[0].req
            if req.duration is not None:
                kwargs["duration"] = req.duration
            if req.speed != 1.0:
                kwargs["speed"] = req.speed
            if req.mode == "design" and req.instruct:
                kwargs["instruct"] = req.instruct
            elif req.mode == "clone" and req.ref_audio_path:
                kwargs["ref_audio"] = req.ref_audio_path
                if req.ref_text:
                    kwargs["ref_text"] = req.ref_text

        try:
            tensors_list = model.generate(**kwargs)
        except TypeError as exc:
            # Fallback: upstream API changed, try minimal kwargs
            logger.warning(
                f"Batched model.generate() raised TypeError: {exc}. "
                "Falling back to sequential single-item calls."
            )
            return self._fallback_sequential(batch, param_key)
        finally:
            _cleanup_memory(self._cfg.device)

        latency_s = time.monotonic() - t0

        # model.generate() returns list[Tensor] — one per input
        # For single input, it's still a list of tensors (possibly multiple chunks)
        results: list[SynthesisResult] = []

        if n == 1:
            # Single request: tensors_list is list[Tensor] for that one request
            duration_s = sum(t.shape[-1] for t in tensors_list) / 24_000
            results.append(SynthesisResult(
                tensors=tensors_list,
                duration_s=duration_s,
                latency_s=latency_s,
            ))
        else:
            # Batch: tensors_list has one Tensor per input
            for tensor in tensors_list:
                t_list = [tensor] if tensor.dim() <= 2 else [tensor]
                duration_s = tensor.shape[-1] / 24_000
                results.append(SynthesisResult(
                    tensors=t_list,
                    duration_s=duration_s,
                    latency_s=latency_s,
                ))

        logger.info(
            f"Batch of {n} completed in {latency_s:.2f}s "
            f"(avg {latency_s/n:.2f}s/req)"
        )
        return results

    def _fallback_sequential(
        self,
        batch: list[_PendingRequest],
        param_key: tuple,
    ) -> list[SynthesisResult]:
        """Fall back to sequential single-item generation if batch fails."""
        num_step, guidance_scale, denoise, t_shift, pos_temp, cls_temp = param_key
        results: list[SynthesisResult] = []

        for pr in batch:
            t0 = time.monotonic()
            req = pr.req
            kwargs: dict[str, Any] = {
                "text": req.text,
                "num_step": num_step,
                "guidance_scale": guidance_scale,
                "denoise": denoise,
                "t_shift": t_shift,
                "position_temperature": pos_temp,
                "class_temperature": cls_temp,
            }
            if req.duration is not None:
                kwargs["duration"] = req.duration
            if req.speed != 1.0:
                kwargs["speed"] = req.speed
            if req.mode == "design" and req.instruct:
                kwargs["instruct"] = req.instruct
            elif req.mode == "clone" and req.ref_audio_path:
                kwargs["ref_audio"] = req.ref_audio_path
                if req.ref_text:
                    kwargs["ref_text"] = req.ref_text

            model = self._model_svc.model
            try:
                tensors = model.generate(**kwargs)
            finally:
                _cleanup_memory(self._cfg.device)

            latency_s = time.monotonic() - t0
            duration_s = sum(t.shape[-1] for t in tensors) / 24_000
            results.append(SynthesisResult(
                tensors=tensors,
                duration_s=duration_s,
                latency_s=latency_s,
            ))

        return results


def _cleanup_memory(device: str) -> None:
    """Post-inference memory cleanup."""
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
