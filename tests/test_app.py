from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from omnivoice_server.app import _apply_cuda_allocator_config
from omnivoice_server.config import Settings


def test_apply_cuda_allocator_config_sets_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)

    cfg = Settings(
        device="cuda",
        cuda_alloc_conf="expandable_segments:True",
        profile_dir=tmp_path,
    )

    fake_cuda = SimpleNamespace(is_initialized=lambda: False)
    fake_torch = SimpleNamespace(cuda=fake_cuda)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    _apply_cuda_allocator_config(cfg)

    assert os.environ["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"


def test_apply_cuda_allocator_config_respects_disabled_override(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)

    cfg = Settings(
        device="cuda",
        cuda_alloc_conf="off",
        profile_dir=tmp_path,
    )

    _apply_cuda_allocator_config(cfg)

    assert "PYTORCH_CUDA_ALLOC_CONF" not in os.environ
