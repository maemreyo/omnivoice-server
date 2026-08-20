"""
Loads and holds the OmniVoice model singleton.
Model is loaded once at startup; never reloaded during runtime.
"""

from __future__ import annotations

import asyncio
import gc
import inspect
import logging
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

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
        self._voice_encoder_lock = threading.Lock()
        self._voice_clone_prompt_cache: dict[str, CachedVoiceClonePrompt] = {}
        self._memory_summary: dict[str, float] = {}
        self._low_vram_active = False
        self._low_vram_tokenizer_path: str | None = None
        self._low_vram_dtype: torch.dtype | None = None
        self._faster_whisper_model = None
        self._asr_lock = threading.Lock()
        self._flashinfer_active = False

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
                if self.cfg.low_vram_mode:
                    try:
                        from ..low_vram import load as load_low_vram

                        model = load_low_vram(
                            self.cfg.model_id,
                            device_map=self.cfg.torch_device_map,
                            dtype=dtype,
                            cache_dir=self.cfg.model_cache_dir,
                        )
                        self._low_vram_active = True
                        self._low_vram_tokenizer_path = model._omnivoice_server_tokenizer_path
                        self._low_vram_dtype = dtype
                        logger.info("Loaded vendored OmniVoice 0.1.2 decoder-only tokenizer")
                    except Exception as exc:
                        logger.warning(
                            "Low-VRAM OmniVoice loader unavailable; falling back to standard "
                            "loader: %s",
                            exc,
                        )
                        self._low_vram_active = False
                        self._low_vram_tokenizer_path = None
                        self._low_vram_dtype = None
                        model = None
                    if model is not None:
                        try:
                            test = model.generate(text="test", num_step=4)
                        except Exception as exc:
                            logger.warning(
                                "Low-VRAM model compatibility test failed; falling back "
                                "to standard loader: %s",
                                exc,
                            )
                            self._low_vram_active = False
                            self._low_vram_tokenizer_path = None
                            self._low_vram_dtype = None
                            del model
                            gc.collect()
                            model = None
                        else:
                            if self._has_nan(test):
                                logger.warning(
                                    "Low-VRAM model compatibility test produced NaN; "
                                    "falling back to standard loader"
                                )
                                self._low_vram_active = False
                                self._low_vram_tokenizer_path = None
                                self._low_vram_dtype = None
                                del model
                                gc.collect()
                                model = None
                            else:
                                self._apply_flashinfer(model)
                                self._apply_split_cfg(model)
                                self._instrument_model(model)
                                self._remember_audio_tokenizer_device(model)
                                self._model = model
                                self._memory_summary = self._compute_model_memory_summary(model)
                                break
                from_pretrained_kwargs = {
                    "device_map": self.cfg.torch_device_map,
                    "dtype": dtype,
                }
                skip_encoder_supported = (
                    self.cfg.skip_voice_encoder
                    and self._supports_skip_encoder(OmniVoice)
                )
                if skip_encoder_supported:
                    from_pretrained_kwargs["skip_encoder"] = True
                if self.cfg.model_cache_dir is not None:
                    from_pretrained_kwargs["cache_dir"] = str(self.cfg.model_cache_dir)
                try:
                    model = OmniVoice.from_pretrained(
                        self.cfg.model_id,
                        **from_pretrained_kwargs,
                    )
                except Exception as exc:
                    if not skip_encoder_supported:
                        raise
                    logger.info(
                        "OmniVoice build does not support skip_encoder=True; "
                        "retrying with the standard loader: %s",
                        exc,
                    )
                    from_pretrained_kwargs.pop("skip_encoder", None)
                    model = OmniVoice.from_pretrained(
                        self.cfg.model_id,
                        **from_pretrained_kwargs,
                    )
                if self.cfg.skip_voice_encoder and not skip_encoder_supported:
                    logger.info(
                        "Installed OmniVoice build has no skip_encoder implementation; "
                        "using CPU encoder offload and persistent prompt caching instead"
                    )
                test = model.generate(text="test", num_step=4)
                if self._has_nan(test):
                    logger.warning(f"dtype={dtype} produced NaN, trying next...")
                    del model
                    gc.collect()
                    continue
                self._apply_flashinfer(model)
                self._apply_split_cfg(model)
                self._instrument_model(model)
                self._remember_audio_tokenizer_device(model)
                self._offload_voice_encoder(model)
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

    def _apply_flashinfer(self, model) -> bool:
        if not self.cfg.flashinfer_mode or self.cfg.device != "cuda":
            self._flashinfer_active = False
            return False
        try:
            from ..vendor.omnivoice_flashinfer_012 import apply_flashinfer

            apply_flashinfer(model, enable_cuda_graph=self.cfg.flashinfer_cuda_graph)
            logger.info(
                "FlashInfer acceleration enabled%s",
                " with CUDA graphs" if self.cfg.flashinfer_cuda_graph else "",
            )
            self._flashinfer_active = True
            return True
        except Exception as exc:
            logger.warning("FlashInfer unavailable or incompatible; using standard path: %s", exc)
            self._flashinfer_active = False
            return False

    def _apply_split_cfg(self, model) -> None:
        if not self.cfg.split_cfg_batch or self._flashinfer_active:
            return
        try:
            from ..optimizations import apply_split_cfg_batch

            apply_split_cfg_batch(model)
            logger.info("Split-CFG standard inference enabled")
        except Exception as exc:
            logger.warning("Split-CFG optimization unavailable; using standard path: %s", exc)

    def transcribe_reference(self, ref_audio_path: str) -> str | None:
        """Transcribe a reference with optional Faster-Whisper, if selected."""
        if self.cfg.transcriber != "faster-whisper":
            return None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.warning(
                "Faster-Whisper selected but not installed; falling back to OmniVoice Whisper"
            )
            return None

        with self._asr_lock:
            if self._faster_whisper_model is None:
                device = self.cfg.asr_device
                if device == "auto":
                    device = "cuda" if self.cfg.device == "cuda" else "cpu"
                compute_type = "float16" if device == "cuda" else "int8"
                self._faster_whisper_model = WhisperModel(
                    self.cfg.asr_model_name,
                    device=device,
                    compute_type=compute_type,
                )
            kwargs = {"beam_size": self.cfg.asr_beam_size}
            if self.cfg.asr_language:
                kwargs["language"] = self.cfg.asr_language
            segments, _ = self._faster_whisper_model.transcribe(ref_audio_path, **kwargs)
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
        return transcript or None

    def _dtype_candidates(self) -> list:
        if self.cfg.device in ("cuda", "mps"):
            if self.cfg.device == "cuda" and torch.cuda.is_available():
                capability = torch.cuda.get_device_capability()
                if capability[0] >= 8 and torch.cuda.is_bf16_supported():
                    return [torch.bfloat16, torch.float16, torch.float32]
            return [torch.float16, torch.bfloat16, torch.float32]
        return [torch.float32]

    @staticmethod
    def _has_nan(tensors: torch.Tensor | np.ndarray | list | None) -> bool:
        np: types.ModuleType | None
        try:
            import numpy as np
        except Exception:
            np = None

        def contains_nan(x) -> bool:
            if x is None:
                return False
            # Check numpy arrays first to avoid calling torch.isnan on ndarray outputs (issue #17).
            if np is not None and isinstance(x, np.ndarray):
                return bool(np.isnan(x).any())
            if torch.is_tensor(x):
                return bool(torch.isnan(x).any().item())
            if isinstance(x, (list, tuple)):
                return any(contains_nan(i) for i in x)
            return False

        return contains_nan(tensors)

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

        disk_prompt = self._load_disk_prompt(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            audio_mtime_ns=stat.st_mtime_ns,
            audio_size=stat.st_size,
        )
        if disk_prompt is not None:
            prompt = disk_prompt
        else:
            prompt_ref_text = ref_text
            if prompt_ref_text is None:
                prompt_ref_text = self.transcribe_reference(ref_audio_path)
            with self._voice_encoder_lock:
                self._restore_voice_encoder()
                try:
                    prompt = self.model.create_voice_clone_prompt(
                        ref_audio=ref_audio_path,
                        ref_text=prompt_ref_text,
                    )
                finally:
                    self._offload_voice_encoder()
            prompt = self._move_prompt_to_cpu(prompt)
            self._save_disk_prompt(
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                audio_mtime_ns=stat.st_mtime_ns,
                audio_size=stat.st_size,
                prompt=prompt,
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
            cached = self._voice_clone_prompt_cache.pop(profile_id, None)
        if cached is not None:
            self._prompt_cache_path(cached.ref_audio_path).unlink(missing_ok=True)

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

    @staticmethod
    def _prompt_cache_path(ref_audio_path: str) -> Path:
        return Path(ref_audio_path).with_suffix(".tokens.pt")

    @staticmethod
    def _move_prompt_to_cpu(prompt):
        """Keep reusable voice tokens off GPU; generation moves them as needed."""
        tokens = getattr(prompt, "ref_audio_tokens", None)
        if not torch.is_tensor(tokens):
            return prompt
        if not tokens.is_cuda and tokens.device.type == "cpu":
            return prompt
        prompt_type = type(prompt)
        return prompt_type(
            ref_audio_tokens=tokens.detach().to("cpu"),
            ref_text=prompt.ref_text,
            ref_rms=prompt.ref_rms,
        )

    def _load_disk_prompt(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        audio_mtime_ns: int,
        audio_size: int,
    ):
        cache_path = self._prompt_cache_path(ref_audio_path)
        if not cache_path.is_file():
            return None
        try:
            payload = torch.load(cache_path, map_location="cpu", weights_only=True)
            if not isinstance(payload, dict):
                return None
            cached_text = payload.get("ref_text")
            has_source_metadata = "audio_mtime_ns" in payload and "audio_size" in payload
            if has_source_metadata:
                if (
                    payload.get("audio_mtime_ns") != audio_mtime_ns
                    or payload.get("audio_size") != audio_size
                ):
                    return None
                if cached_text != ref_text:
                    return None
            else:
                # Sonorus-compatible sidecars contain audio_codes, ref_rms, and
                # ref_text. Reuse them only when newer than the source audio.
                if cache_path.stat().st_mtime_ns < audio_mtime_ns:
                    return None
                if ref_text is not None and cached_text != ref_text:
                    return None
            tokens = payload.get("audio_codes", payload.get("ref_audio_tokens"))
            if not torch.is_tensor(tokens) or tokens.ndim != 2 or tokens.numel() == 0:
                return None
            from omnivoice.models.omnivoice import VoiceClonePrompt

            return VoiceClonePrompt(
                ref_audio_tokens=tokens.to("cpu"),
                ref_text=str(payload.get("prompt_ref_text", cached_text)),
                ref_rms=float(payload["ref_rms"]),
            )
        except Exception as exc:
            logger.warning("Ignoring invalid voice prompt cache %s: %s", cache_path, exc)
            return None

    def _save_disk_prompt(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        audio_mtime_ns: int,
        audio_size: int,
        prompt,
    ) -> None:
        tokens = getattr(prompt, "ref_audio_tokens", None)
        if not torch.is_tensor(tokens):
            return
        cache_path = self._prompt_cache_path(ref_audio_path)
        temporary = cache_path.with_name(f".{cache_path.name}.{threading.get_ident()}.tmp")
        try:
            torch.save(
                {
                    "audio_mtime_ns": audio_mtime_ns,
                    "audio_size": audio_size,
                    "ref_text": ref_text,
                    "prompt_ref_text": prompt.ref_text,
                    "ref_rms": float(prompt.ref_rms),
                    "audio_codes": tokens.detach().to("cpu"),
                },
                temporary,
            )
            temporary.replace(cache_path)
        except Exception as exc:
            logger.warning("Could not persist voice prompt cache %s: %s", cache_path, exc)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _remember_audio_tokenizer_device(model) -> None:
        tokenizer = getattr(model, "audio_tokenizer", None)
        if tokenizer is None:
            return
        # The tokenizer becomes a heterogeneous module after reference-encoder
        # offload. PreTrainedModel.device returns the device of its first
        # parameter, which is then CPU even though decode layers remain on the
        # accelerator. fc2 is the first projection used by decode(), so prefer
        # its device and retain it before moving encoder-only modules.
        decoder_projection = getattr(tokenizer, "fc2", None)
        device_source = decoder_projection if decoder_projection is not None else tokenizer
        try:
            model._omnivoice_server_audio_tokenizer_device = next(
                device_source.parameters()
            ).device
        except StopIteration:
            model._omnivoice_server_audio_tokenizer_device = None

    @staticmethod
    def _supports_skip_encoder(omnivoice_cls) -> bool:
        try:
            return "skip_encoder" in inspect.getsource(omnivoice_cls.from_pretrained)
        except (OSError, TypeError):
            return False

    def _restore_voice_encoder(self) -> None:
        if self._low_vram_active:
            from ..low_vram import load_encoder_modules

            tokenizer = getattr(self.model, "audio_tokenizer", None)
            if tokenizer is None or self._low_vram_tokenizer_path is None:
                raise RuntimeError("low-VRAM tokenizer metadata is missing")
            if self._low_vram_dtype is None:
                raise RuntimeError("low-VRAM tokenizer dtype is missing")
            modules = load_encoder_modules(self._low_vram_tokenizer_path, self._low_vram_dtype)
            device = getattr(self.model, "_omnivoice_server_audio_tokenizer_device", None)
            for name, module in modules.items():
                setattr(tokenizer, name, module.to(device))
            return
        if not self.cfg.offload_voice_encoder:
            return
        tokenizer = getattr(self.model, "audio_tokenizer", None)
        device = getattr(self.model, "_omnivoice_server_audio_tokenizer_device", None)
        if tokenizer is None or device is None:
            return
        for name in ("semantic_model", "acoustic_encoder", "encoder_semantic", "fc", "fc1"):
            module = getattr(tokenizer, name, None)
            if module is not None:
                module.to(device)

    def _offload_voice_encoder(self, model=None) -> None:
        if self._low_vram_active:
            from ..low_vram import ENCODER_MODULES

            model = model or self.model
            tokenizer = getattr(model, "audio_tokenizer", None)
            if tokenizer is not None:
                for name in ENCODER_MODULES:
                    if hasattr(tokenizer, name):
                        setattr(tokenizer, name, None)
            gc.collect()
            if self.cfg.device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()
            return
        if not self.cfg.offload_voice_encoder:
            return
        model = model or self.model
        tokenizer = getattr(model, "audio_tokenizer", None)
        if tokenizer is None:
            return
        for name in ("semantic_model", "acoustic_encoder", "encoder_semantic", "fc", "fc1"):
            module = getattr(tokenizer, name, None)
            if module is not None:
                module.to("cpu")
        if self.cfg.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()

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
        tokenizer = getattr(model, "audio_tokenizer", None)
        if tokenizer is not None and hasattr(tokenizer, "decode"):
            tokenizer.decode = self._wrap_audio_tokenizer_decode(tokenizer.decode, model)

        model._omnivoice_server_timing_instrumented = True

    @staticmethod
    def _wrap_audio_tokenizer_decode(fn, model):
        """Move audio codes to the decoder device after encoder CPU offload."""

        def wrapped(audio_codes, *args, __fn=fn, __model=model, **kwargs):
            device = getattr(
                __model,
                "_omnivoice_server_audio_tokenizer_device",
                None,
            )
            if device is not None and torch.is_tensor(audio_codes):
                audio_codes = audio_codes.to(device)
            return __fn(audio_codes, *args, **kwargs)

        return wrapped

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
            [
                (name, tensor)
                for name, tensor in named_parameters
                if name.startswith("audio_tokenizer.")
            ]
        )
        audio_buffer_bytes = _bytes(
            [
                (name, tensor)
                for name, tensor in named_buffers
                if name.startswith("audio_tokenizer.")
            ]
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
