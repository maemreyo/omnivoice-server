"""Pinned OmniVoice 0.1.2 loader for the opt-in low-VRAM path.

This module deliberately keeps the compatibility surface small.  The normal
OmniVoice loader remains the default; callers can treat any exception here as
an incompatibility and fall back to it.
"""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path
from typing import Any

import torch

from .vendor.omnivoice_012 import OmniVoice

logger = logging.getLogger(__name__)

ENCODER_MODULES = ("semantic_model", "acoustic_encoder", "encoder_semantic", "fc", "fc1")


def _is_encoder_key(key: str) -> bool:
    return any(key == name or key.startswith(f"{name}.") for name in ENCODER_MODULES)


def _resolve_model_path(model_id: str, cache_dir: Path | None) -> str:
    if os.path.isdir(model_id):
        return model_id
    from huggingface_hub import snapshot_download

    if cache_dir is not None:
        return snapshot_download(repo_id=model_id, cache_dir=cache_dir)
    return snapshot_download(repo_id=model_id)


def _tokenizer_path(model_path: str) -> str:
    path = os.path.join(model_path, "audio_tokenizer")
    if not os.path.isdir(path):
        raise RuntimeError("model has no local audio_tokenizer directory")
    return path


def _load_safetensors(path: str, *, include_encoder: bool) -> dict[str, torch.Tensor]:
    filename = os.path.join(path, "model.safetensors")
    if not os.path.isfile(filename):
        raise RuntimeError(f"missing selective tokenizer weights: {filename}")
    try:
        from safetensors.torch import load_file
    except ImportError as exc:
        raise RuntimeError("safetensors is required by the low-VRAM loader") from exc
    state = load_file(filename, device="cpu")
    if include_encoder:
        return {key: value for key, value in state.items() if _is_encoder_key(key)}
    return {key: value for key, value in state.items() if not _is_encoder_key(key)}


def _make_tokenizer(tokenizer_path: str, device: str, dtype: torch.dtype):
    from transformers import AutoFeatureExtractor, HiggsAudioV2TokenizerModel

    config = HiggsAudioV2TokenizerModel.config_class.from_pretrained(tokenizer_path)
    tokenizer: Any = HiggsAudioV2TokenizerModel(config)
    state = _load_safetensors(tokenizer_path, include_encoder=False)
    missing, unexpected = tokenizer.load_state_dict(state, strict=False)
    unexpected = list(unexpected)
    allowed_missing = [key for key in missing if _is_encoder_key(key)]
    if unexpected or len(allowed_missing) != len(missing):
        raise RuntimeError(
            "selective tokenizer weights do not match OmniVoice 0.1.2: "
            f"missing={missing[:4]}, unexpected={unexpected[:4]}"
        )
    for name in ENCODER_MODULES:
        if hasattr(tokenizer, name):
            setattr(tokenizer, name, None)
    tokenizer = tokenizer.to(device=device, dtype=dtype).eval()
    feature_extractor = AutoFeatureExtractor.from_pretrained(tokenizer_path)
    return tokenizer, feature_extractor


def load(model_id: str, *, device_map: str, dtype: torch.dtype, cache_dir: Path | None = None):
    """Load the main model and a decoder-only audio tokenizer."""
    model_path = _resolve_model_path(model_id, cache_dir)
    tokenizer_path = _tokenizer_path(model_path)
    model = OmniVoice.from_pretrained(
        model_path,
        train=True,
        device_map=device_map,
        dtype=dtype,
    )
    from transformers import AutoTokenizer

    model.text_tokenizer = AutoTokenizer.from_pretrained(model_path)
    tokenizer, feature_extractor = _make_tokenizer(tokenizer_path, device_map, dtype)
    model.audio_tokenizer = tokenizer
    model.feature_extractor = feature_extractor
    model.sampling_rate = feature_extractor.sampling_rate
    from omnivoice.utils.duration import RuleDurationEstimator

    model.duration_estimator = RuleDurationEstimator()
    model._omnivoice_server_low_vram = True
    model._omnivoice_server_tokenizer_path = tokenizer_path
    model._omnivoice_server_tokenizer_dtype = dtype
    return model


def load_encoder_modules(tokenizer_path: str, dtype: torch.dtype) -> dict[str, Any]:
    """Rebuild only encoder module objects and load their checkpoint keys."""
    from transformers import HiggsAudioV2TokenizerModel

    config = HiggsAudioV2TokenizerModel.config_class.from_pretrained(tokenizer_path)
    tokenizer = HiggsAudioV2TokenizerModel(config)
    state = _load_safetensors(tokenizer_path, include_encoder=True)
    modules: dict[str, Any] = {}
    for name in ENCODER_MODULES:
        module = getattr(tokenizer, name, None)
        if module is None:
            continue
        prefix = f"{name}."
        module_state = {
            key[len(prefix):]: value
            for key, value in state.items()
            if key.startswith(prefix)
        }
        if module_state:
            missing, unexpected = module.load_state_dict(module_state, strict=False)
            if unexpected or missing:
                raise RuntimeError(
                    f"encoder module {name} mismatch: {missing[:2]}, {unexpected[:2]}"
                )
        modules[name] = module.to(dtype=dtype).eval()
    del tokenizer
    gc.collect()
    if not modules:
        raise RuntimeError("tokenizer checkpoint contains no supported encoder modules")
    return modules
