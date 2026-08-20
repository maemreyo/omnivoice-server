from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import torch
from omnivoice.models.omnivoice import VoiceClonePrompt

from omnivoice_server.config import Settings
from omnivoice_server.services.inference import InferenceService, SynthesisRequest
from omnivoice_server.services.model import ModelService


class FakeOmniVoiceModel:
    def __init__(self) -> None:
        self.prompt_calls = 0
        self.generate_calls: list[dict] = []

    def create_voice_clone_prompt(self, ref_audio, ref_text=None, preprocess_prompt=True):
        self.prompt_calls += 1
        return {
            "prompt_call": self.prompt_calls,
            "ref_audio": ref_audio,
            "ref_text": ref_text,
            "preprocess_prompt": preprocess_prompt,
        }

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return [torch.zeros(1, 24_000)]


def _make_model_service(tmp_path):
    cfg = Settings(
        device="cpu",
        profile_dir=tmp_path / "profiles",
    )
    model_svc = ModelService(cfg)
    model_svc._model = FakeOmniVoiceModel()
    model_svc._loaded = True
    return cfg, model_svc


def test_inference_uses_cached_voice_clone_prompt_for_profiles(tmp_path):
    cfg, model_svc = _make_model_service(tmp_path)
    ref_audio_path = tmp_path / "sky.wav"
    ref_audio_path.write_bytes(b"fake wav bytes")

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        inference_svc = InferenceService(model_svc=model_svc, executor=executor, cfg=cfg)
        req = SynthesisRequest(
            text="Hello from cache",
            mode="clone",
            ref_audio_path=str(ref_audio_path),
            ref_text="Reference transcript",
            profile_id="sky",
        )

        first = inference_svc._run_sync(req)
        second = inference_svc._run_sync(req)
    finally:
        executor.shutdown(wait=False)

    fake_model = model_svc.model
    assert fake_model.prompt_calls == 1
    assert len(fake_model.generate_calls) == 2
    assert "voice_clone_prompt" in fake_model.generate_calls[0]
    assert "voice_clone_prompt" in fake_model.generate_calls[1]
    assert "ref_audio" not in fake_model.generate_calls[0]
    assert "ref_audio" not in fake_model.generate_calls[1]
    assert first.duration_s == 1.0
    assert second.duration_s == 1.0


def test_prepare_clone_request_reuses_one_shot_prompt_for_streaming(tmp_path):
    cfg, model_svc = _make_model_service(tmp_path)
    ref_audio_path = tmp_path / "one-shot.wav"
    ref_audio_path.write_bytes(b"fake wav bytes")

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        inference_svc = InferenceService(model_svc=model_svc, executor=executor, cfg=cfg)
        req = SynthesisRequest(
            text="First sentence.",
            mode="clone",
            ref_audio_path=str(ref_audio_path),
            ref_text="Reference transcript",
        )
        prepared = asyncio.run(inference_svc.prepare_clone_request(req))
        second = replace(prepared, text="Second sentence.")
        inference_svc._run_sync(prepared)
        inference_svc._run_sync(second)
    finally:
        executor.shutdown(wait=False)

    fake_model = model_svc.model
    assert fake_model.prompt_calls == 1
    assert all("voice_clone_prompt" in call for call in fake_model.generate_calls)


def test_voice_clone_prompt_persists_as_cpu_token_cache(tmp_path):
    class PromptModel(FakeOmniVoiceModel):
        def create_voice_clone_prompt(self, ref_audio, ref_text=None, preprocess_prompt=True):
            self.prompt_calls += 1
            return VoiceClonePrompt(
                ref_audio_tokens=torch.ones(8, 4, dtype=torch.long),
                ref_text="Reference transcript.",
                ref_rms=0.25,
            )

    cfg, model_svc = _make_model_service(tmp_path)
    model_svc._model = PromptModel()
    ref_audio_path = tmp_path / "sky.wav"
    ref_audio_path.write_bytes(b"fake wav bytes")
    req = SynthesisRequest(
        text="Hello from disk cache",
        mode="clone",
        ref_audio_path=str(ref_audio_path),
        ref_text="Reference transcript",
        profile_id="sky",
    )

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        first_service = InferenceService(model_svc=model_svc, executor=executor, cfg=cfg)
        first_service._run_sync(req)
    finally:
        executor.shutdown(wait=False)

    cache_path = ref_audio_path.with_suffix(".tokens.pt")
    assert cache_path.is_file()

    second_cfg, second_model_svc = _make_model_service(tmp_path)
    second_model = PromptModel()
    second_model_svc._model = second_model
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        second_service = InferenceService(
            model_svc=second_model_svc,
            executor=executor,
            cfg=second_cfg,
        )
        second_service._run_sync(req)
    finally:
        executor.shutdown(wait=False)

    assert second_model.prompt_calls == 0
    cached_prompt = second_model.generate_calls[0]["voice_clone_prompt"]
    assert cached_prompt.ref_audio_tokens.device.type == "cpu"


def test_cleanup_is_disabled_by_default(monkeypatch, tmp_path):
    cfg, model_svc = _make_model_service(tmp_path)
    cleanup_calls: list[str] = []

    def fake_cleanup(device: str) -> None:
        cleanup_calls.append(device)

    monkeypatch.setattr("omnivoice_server.services.inference._cleanup_memory", fake_cleanup)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        inference_svc = InferenceService(model_svc=model_svc, executor=executor, cfg=cfg)
        result = inference_svc._run_sync(SynthesisRequest(text="Hello", mode="auto"))
    finally:
        executor.shutdown(wait=False)

    assert cleanup_calls == []
    assert result.breakdown is not None
    assert result.breakdown.cleanup_ms == 0.0


def test_cleanup_interval_runs_periodically(monkeypatch, tmp_path):
    cfg, model_svc = _make_model_service(tmp_path)
    cfg.cleanup_interval = 2
    cleanup_calls: list[str] = []

    def fake_cleanup(device: str) -> None:
        cleanup_calls.append(device)

    monkeypatch.setattr("omnivoice_server.services.inference._cleanup_memory", fake_cleanup)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        inference_svc = InferenceService(model_svc=model_svc, executor=executor, cfg=cfg)
        inference_svc._run_sync(SynthesisRequest(text="Hello one", mode="auto"))
        result = inference_svc._run_sync(SynthesisRequest(text="Hello two", mode="auto"))
    finally:
        executor.shutdown(wait=False)

    assert cleanup_calls == ["cpu"]
    assert result.breakdown is not None
    assert result.breakdown.cleanup_ms >= 0.0
