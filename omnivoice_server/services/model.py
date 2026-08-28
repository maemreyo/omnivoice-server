"""
Loads and holds the OmniVoice model singleton.
Model is loaded once at startup; never reloaded during runtime.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
import types
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

import psutil
import torch

if TYPE_CHECKING:
    from omnivoice import OmniVoice

from ..config import Settings

logger = logging.getLogger(__name__)


class ModelService:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._model = None
        self._loaded = False

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
                from_pretrained_kwargs = {
                    "device_map": self.cfg.torch_device_map,
                    "dtype": dtype,
                }
                if self.cfg.model_cache_dir is not None:
                    from_pretrained_kwargs["cache_dir"] = str(self.cfg.model_cache_dir)
                model = OmniVoice.from_pretrained(
                    self.cfg.model_id,
                    **from_pretrained_kwargs,
                )
                test = model.generate(text="test", num_step=4)
                if self._has_nan(test):
                    logger.warning(f"dtype={dtype} produced NaN, trying next...")
                    del model
                    gc.collect()
                    continue
                self._model = model
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
        if self.cfg.device in ("cuda", "mps"):
            return [torch.float16, torch.bfloat16, torch.float32]
        return [torch.float32]

    @staticmethod
    def _has_nan(tensors: torch.Tensor | np.ndarray | list | None) -> bool:
        # Declared then assigned, rather than `import numpy as np` into an
        # annotated name: the latter is a redefinition, which mypy rejects.
        numpy_mod: types.ModuleType | None
        try:
            import numpy

            numpy_mod = numpy
        except Exception:
            numpy_mod = None

        def contains_nan(x) -> bool:
            if x is None:
                return False
            # Check numpy arrays first to avoid calling torch.isnan on ndarray outputs (issue #17).
            if numpy_mod is not None and isinstance(x, numpy_mod.ndarray):
                return bool(numpy_mod.isnan(x).any())
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


def _get_ram_mb() -> float:
    return psutil.Process().memory_info().rss / 1024 / 1024
