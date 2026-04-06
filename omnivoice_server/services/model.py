"""
Loads and holds the OmniVoice model singleton.
Model is loaded once at startup; never reloaded during runtime.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil
import torch

if TYPE_CHECKING:
    from omnivoice import OmniVoice

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ModelTimingBreakdown:
    clone_prompt_ms: float = 0.0
    clone_prompt_calls: int = 0
    decode_postprocess_ms: float = 0.0
    decode_postprocess_calls: int = 0
    postprocess_ms: float = 0.0
    postprocess_calls: int = 0
    prepare_inference_calls: int = 0
    batch_size: int = 0
    max_condition_len: int = 0
    max_target_tokens: int = 0
    max_ref_audio_tokens: int = 0
    attention_mask_mb_estimate: float = 0.0
    batch_logits_mb_estimate: float = 0.0
    tokens_mb_estimate: float = 0.0

    @property
    def decode_only_ms(self) -> float:
        return max(0.0, self.decode_postprocess_ms - self.postprocess_ms)


@dataclass
class CachedVoiceClonePrompt:
    prompt: Any
    ref_audio_path: str
    ref_text: str | None
    audio_mtime_ns: int
    audio_size: int


class ModelService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._model = None
        self._loaded = False
        self._timing_local = threading.local()
        self._prompt_cache_lock = threading.Lock()
        self._voice_clone_prompt_cache: dict[str, CachedVoiceClonePrompt] = {}
        self._memory_summary: dict[str, float] = {}

    async def load(self) -> None:
        """Load model in a thread (blocking op, must not block event loop)."""
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(ex, self._load_sync)

    def _load_sync(self) -> None:
        from omnivoice import OmniVoice

        ram_before = _get_ram_mb()
        t0 = time.monotonic()

        logger.info(f"Loading model '{self.cfg.model_id}' on {self.cfg.device}...")

        for dtype in self._dtype_candidates():
            try:
                model = OmniVoice.from_pretrained(
                    self.cfg.model_id,
                    device_map=self.cfg.torch_device_map,
                    dtype=dtype,
                )
                test = model.generate(text="test", num_step=4)
                if self._has_nan(test):
                    logger.warning(f"dtype={dtype} produced NaN, trying next...")
                    del model
                    gc.collect()
                    continue
                self._instrument_model(model)
                self._model = model
                self._memory_summary = self._compute_model_memory_summary(model)
                break
            except Exception as e:
                logger.warning(f"Failed to load with dtype={dtype}: {e}")
                continue

        if self._model is None:
            raise RuntimeError(
                f"Failed to load OmniVoice on device={self.cfg.device}. "
                "Try --device cpu or check GPU/MPS availability."
            )

        elapsed = time.monotonic() - t0
        ram_after = _get_ram_mb()
        logger.info(
            f"Model loaded in {elapsed:.1f}s. "
            f"RAM: {ram_before:.0f}MB -> {ram_after:.0f}MB "
            f"(+{ram_after - ram_before:.0f}MB)"
        )
        self._loaded = True

    def _dtype_candidates(self) -> list:
        if self.cfg.device == "cuda":
            return [torch.float16, torch.bfloat16, torch.float32]
        if self.cfg.device == "mps":
            return [torch.float16, torch.bfloat16, torch.float32]
        return [torch.float32]

    @staticmethod
    def _has_nan(tensors: list) -> bool:
        return any(torch.isnan(t).any() for t in tensors)

    @property
    def model(self) -> OmniVoice:
        if not self._loaded:
            raise RuntimeError("Model not loaded yet")
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def begin_timing_capture(self) -> None:
        self._timing_local.trace = ModelTimingBreakdown()

    def end_timing_capture(self) -> ModelTimingBreakdown:
        trace = getattr(self._timing_local, "trace", None)
        if hasattr(self._timing_local, "trace"):
            del self._timing_local.trace
        return trace or ModelTimingBreakdown()

    def get_or_create_voice_clone_prompt(
        self,
        profile_id: str,
        ref_audio_path: str,
        ref_text: str | None,
    ):
        audio_path = Path(ref_audio_path)
        stat = audio_path.stat()

        with self._prompt_cache_lock:
            cached = self._voice_clone_prompt_cache.get(profile_id)
            if cached and self._cache_matches(
                cached=cached,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                audio_mtime_ns=stat.st_mtime_ns,
                audio_size=stat.st_size,
            ):
                return cached.prompt

        prompt = self.model.create_voice_clone_prompt(
            ref_audio=ref_audio_path,
            ref_text=ref_text,
        )

        with self._prompt_cache_lock:
            self._voice_clone_prompt_cache[profile_id] = CachedVoiceClonePrompt(
                prompt=prompt,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                audio_mtime_ns=stat.st_mtime_ns,
                audio_size=stat.st_size,
            )

        return prompt

    def invalidate_voice_clone_prompt(self, profile_id: str | None = None) -> None:
        with self._prompt_cache_lock:
            if profile_id is None:
                self._voice_clone_prompt_cache.clear()
                return
            self._voice_clone_prompt_cache.pop(profile_id, None)

    def debug_snapshot(self) -> dict[str, float | int]:
        snapshot: dict[str, float | int] = {
            "model_core_params_mb": 0.0,
            "model_core_buffers_mb": 0.0,
            "model_audio_tokenizer_params_mb": 0.0,
            "model_audio_tokenizer_buffers_mb": 0.0,
            "model_total_params_mb": 0.0,
            "model_total_buffers_mb": 0.0,
        }
        snapshot.update(self._memory_summary)

        with self._prompt_cache_lock:
            snapshot["prompt_cache_entries"] = len(self._voice_clone_prompt_cache)
            cache_cuda_bytes = 0
            cache_cpu_bytes = 0
            for cached in self._voice_clone_prompt_cache.values():
                prompt = cached.prompt
                ref_audio_tokens = getattr(prompt, "ref_audio_tokens", None)
                if ref_audio_tokens is None:
                    continue
                token_bytes = ref_audio_tokens.numel() * ref_audio_tokens.element_size()
                if getattr(ref_audio_tokens, "is_cuda", False):
                    cache_cuda_bytes += token_bytes
                else:
                    cache_cpu_bytes += token_bytes

        snapshot["prompt_cache_cuda_mb"] = round(cache_cuda_bytes / 1024 / 1024, 3)
        snapshot["prompt_cache_cpu_mb"] = round(cache_cpu_bytes / 1024 / 1024, 3)
        return snapshot

    def _instrument_model(self, model) -> None:
        if getattr(model, "_omnivoice_server_timing_instrumented", False):
            return

        if hasattr(model, "create_voice_clone_prompt"):
            model.create_voice_clone_prompt = self._wrap_timed_call(
                model.create_voice_clone_prompt,
                timing_name="clone_prompt",
            )
        if hasattr(model, "_decode_and_post_process"):
            model._decode_and_post_process = self._wrap_timed_call(
                model._decode_and_post_process,
                timing_name="decode_postprocess",
            )
        if hasattr(model, "_post_process_audio"):
            model._post_process_audio = self._wrap_timed_call(
                model._post_process_audio,
                timing_name="postprocess",
            )
        if hasattr(model, "_prepare_inference_inputs"):
            model._prepare_inference_inputs = self._wrap_prepare_inference_inputs(
                model._prepare_inference_inputs
            )
        if hasattr(model, "_generate_iterative"):
            model._generate_iterative = self._wrap_generate_iterative(
                model._generate_iterative,
                model,
            )

        model._omnivoice_server_timing_instrumented = True

    def _wrap_timed_call(self, fn, timing_name: str):
        def wrapped(*args, __fn=fn, **kwargs):
            started = time.monotonic()
            try:
                return __fn(*args, **kwargs)
            finally:
                self._record_timing(
                    timing_name=timing_name,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )

        return wrapped

    def _record_timing(self, timing_name: str, elapsed_ms: float) -> None:
        trace = getattr(self._timing_local, "trace", None)
        if trace is None:
            return

        if timing_name == "clone_prompt":
            trace.clone_prompt_ms += elapsed_ms
            trace.clone_prompt_calls += 1
        elif timing_name == "decode_postprocess":
            trace.decode_postprocess_ms += elapsed_ms
            trace.decode_postprocess_calls += 1
        elif timing_name == "postprocess":
            trace.postprocess_ms += elapsed_ms
            trace.postprocess_calls += 1

    def _wrap_prepare_inference_inputs(self, fn):
        def wrapped(
            text,
            num_target_tokens,
            ref_text=None,
            ref_audio_tokens=None,
            lang=None,
            instruct=None,
            denoise=True,
            __fn=fn,
        ):
            result = __fn(
                text,
                num_target_tokens,
                ref_text=ref_text,
                ref_audio_tokens=ref_audio_tokens,
                lang=lang,
                instruct=instruct,
                denoise=denoise,
            )
            trace = getattr(self._timing_local, "trace", None)
            if trace is None:
                return result

            trace.prepare_inference_calls += 1
            trace.batch_size = max(trace.batch_size, int(result["input_ids"].size(0)))
            trace.max_condition_len = max(trace.max_condition_len, int(result["input_ids"].size(2)))
            trace.max_target_tokens = max(trace.max_target_tokens, int(num_target_tokens))
            ref_audio_len = ref_audio_tokens.size(-1) if ref_audio_tokens is not None else 0
            trace.max_ref_audio_tokens = max(trace.max_ref_audio_tokens, int(ref_audio_len))
            return result

        return wrapped

    def _wrap_generate_iterative(self, fn, model):
        def wrapped(task, gen_config, __fn=fn, __model=model):
            trace = getattr(self._timing_local, "trace", None)
            if trace is not None:
                batch_size = int(task.batch_size)
                max_condition_len = int(trace.max_condition_len)
                max_target_tokens = max((int(t) for t in task.target_lens), default=0)
                num_codebooks = int(__model.config.num_audio_codebook)
                audio_vocab_size = int(__model.config.audio_vocab_size)

                trace.batch_size = max(trace.batch_size, batch_size)
                trace.max_target_tokens = max(trace.max_target_tokens, max_target_tokens)

                if max_condition_len > 0:
                    trace.attention_mask_mb_estimate = max(
                        trace.attention_mask_mb_estimate,
                        (2 * batch_size * max_condition_len * max_condition_len) / 1024 / 1024,
                    )
                    trace.batch_logits_mb_estimate = max(
                        trace.batch_logits_mb_estimate,
                        (
                            2
                            * batch_size
                            * num_codebooks
                            * max_condition_len
                            * audio_vocab_size
                            * 4
                        )
                        / 1024
                        / 1024,
                    )
                if max_target_tokens > 0:
                    trace.tokens_mb_estimate = max(
                        trace.tokens_mb_estimate,
                        (batch_size * num_codebooks * max_target_tokens * 8) / 1024 / 1024,
                    )

            return __fn(task, gen_config)

        return wrapped

    @staticmethod
    def _cache_matches(
        cached: CachedVoiceClonePrompt,
        ref_audio_path: str,
        ref_text: str | None,
        audio_mtime_ns: int,
        audio_size: int,
    ) -> bool:
        return (
            cached.ref_audio_path == ref_audio_path
            and cached.ref_text == ref_text
            and cached.audio_mtime_ns == audio_mtime_ns
            and cached.audio_size == audio_size
        )

    @staticmethod
    def _compute_model_memory_summary(model) -> dict[str, float]:
        named_parameters = list(model.named_parameters())
        named_buffers = list(model.named_buffers())

        def _bytes(items) -> int:
            return sum(t.numel() * t.element_size() for _, t in items)

        audio_param_bytes = _bytes(
            [(name, tensor) for name, tensor in named_parameters if name.startswith("audio_tokenizer.")]
        )
        audio_buffer_bytes = _bytes(
            [(name, tensor) for name, tensor in named_buffers if name.startswith("audio_tokenizer.")]
        )
        total_param_bytes = _bytes(named_parameters)
        total_buffer_bytes = _bytes(named_buffers)
        core_param_bytes = total_param_bytes - audio_param_bytes
        core_buffer_bytes = total_buffer_bytes - audio_buffer_bytes

        return {
            "model_core_params_mb": round(core_param_bytes / 1024 / 1024, 1),
            "model_core_buffers_mb": round(core_buffer_bytes / 1024 / 1024, 1),
            "model_audio_tokenizer_params_mb": round(audio_param_bytes / 1024 / 1024, 1),
            "model_audio_tokenizer_buffers_mb": round(audio_buffer_bytes / 1024 / 1024, 1),
            "model_total_params_mb": round(total_param_bytes / 1024 / 1024, 1),
            "model_total_buffers_mb": round(total_buffer_bytes / 1024 / 1024, 1),
        }


def _get_ram_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024
