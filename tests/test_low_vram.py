from __future__ import annotations

import os

import torch

from omnivoice_server.config import Settings
from omnivoice_server.low_vram import _is_encoder_key
from omnivoice_server.services.model import ModelService


def test_low_vram_is_explicit_and_environment_configurable():
    assert Settings().low_vram_mode is False
    previous = os.environ.get("OMNIVOICE_LOW_VRAM_MODE")
    os.environ["OMNIVOICE_LOW_VRAM_MODE"] = "true"
    try:
        assert Settings().low_vram_mode is True
    finally:
        if previous is None:
            os.environ.pop("OMNIVOICE_LOW_VRAM_MODE", None)
        else:
            os.environ["OMNIVOICE_LOW_VRAM_MODE"] = previous


def test_selective_loader_key_filter_matches_encoder_boundaries():
    assert _is_encoder_key("semantic_model.layer.weight")
    assert _is_encoder_key("acoustic_encoder.conv.weight")
    assert _is_encoder_key("fc1.bias")
    assert not _is_encoder_key("decoder_semantic.layer.weight")
    assert not _is_encoder_key("acoustic_decoder.conv.weight")


def test_corrupt_prompt_sidecar_is_ignored(tmp_path):
    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"reference")
    cache_path = audio_path.with_suffix(".tokens.pt")
    cache_path.write_bytes(b"not a torch archive")

    service = ModelService(Settings(device="cpu", profile_dir=tmp_path))
    stat = audio_path.stat()
    assert (
        service._load_disk_prompt(
            str(audio_path),
            None,
            stat.st_mtime_ns,
            stat.st_size,
        )
        is None
    )


def test_prompt_cache_payload_keeps_tokens_on_cpu(tmp_path):
    audio_path = tmp_path / "reference.wav"
    audio_path.write_bytes(b"reference")
    service = ModelService(Settings(device="cpu", profile_dir=tmp_path))

    class Prompt:
        ref_audio_tokens = torch.ones(2, 3, dtype=torch.long)
        ref_text = "hello"
        ref_rms = 0.5

    stat = audio_path.stat()
    service._save_disk_prompt(str(audio_path), "hello", stat.st_mtime_ns, stat.st_size, Prompt())
    prompt = service._load_disk_prompt(str(audio_path), "hello", stat.st_mtime_ns, stat.st_size)
    assert prompt is not None
    assert prompt.ref_audio_tokens.device.type == "cpu"
