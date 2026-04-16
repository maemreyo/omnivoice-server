"""
Loads and holds the OmniVoice model singleton.
Model is loaded once at startup; never reloaded during runtime.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

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
    def _has_nan(tensors: list) -> bool:
        try:
            import numpy as np
        except Exception:
            np = None

        def contains_nan(x) -> bool:
            if x is None:
                return False
            if torch.is_tensor(x):
                return bool(torch.isnan(x).any().item())
            if np is not None and isinstance(x, np.ndarray):
                return bool(np.isnan(x).any())
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
