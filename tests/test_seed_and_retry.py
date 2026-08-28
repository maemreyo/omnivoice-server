"""
Seed plumbing and degenerate-output retry (issue #37, groundwork for #38).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
import torch

from omnivoice_server.config import Settings
from omnivoice_server.services.inference import InferenceService, SynthesisRequest

SAMPLE_RATE = 24_000


def _speech_like(duration_s: float = 3.0) -> torch.Tensor:
    n = int(SAMPLE_RATE * duration_s)
    t = torch.arange(n, dtype=torch.float32) / SAMPLE_RATE
    return (0.2 * torch.sin(2 * torch.pi * 220 * t)).unsqueeze(0)


def _mostly_silent(duration_s: float = 7.0) -> torch.Tensor:
    n = int(SAMPLE_RATE * duration_s)
    out = torch.full((n,), 1e-4, dtype=torch.float32)
    out[-int(SAMPLE_RATE * 0.3) :] = 0.3
    return out.unsqueeze(0)


class _FakeModel:
    """Records every generate() call and returns queued outputs in order."""

    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self._outputs.pop(0) if self._outputs else [_speech_like()]


class _FakeModelService:
    def __init__(self, model):
        self.model = model
        self.is_loaded = True


def _service(model, **cfg_kwargs) -> InferenceService:
    cfg = Settings(device="cpu", num_step=4, max_concurrent=1, api_key="", **cfg_kwargs)
    return InferenceService(_FakeModelService(model), ThreadPoolExecutor(max_workers=1), cfg)


def _req(**kwargs) -> SynthesisRequest:
    return SynthesisRequest(text="Hello [laughter] world", mode="auto", **kwargs)


# ── Retry on degenerate output ───────────────────────────────────────────────


def test_degenerate_output_is_retried_deterministically():
    model = _FakeModel([[_mostly_silent()], [_speech_like()]])
    result = _service(model)._run_sync(_req())

    assert len(model.calls) == 2
    assert result.retried is True
    # The retry must remove the sampler freedom that produced the bad roll.
    assert model.calls[0]["position_temperature"] == 5.0
    assert model.calls[1]["position_temperature"] == 0.0


def test_healthy_output_is_not_retried():
    model = _FakeModel([[_speech_like()]])
    result = _service(model)._run_sync(_req())

    assert len(model.calls) == 1
    assert result.retried is False


def test_retry_is_skipped_when_already_deterministic():
    """At position_temperature=0 a retry would reproduce the same output."""
    model = _FakeModel([[_mostly_silent()], [_speech_like()]])
    result = _service(model)._run_sync(_req(position_temperature=0.0))

    assert len(model.calls) == 1
    assert result.retried is False


def test_retry_can_be_disabled():
    model = _FakeModel([[_mostly_silent()], [_speech_like()]])
    result = _service(model, retry_degenerate=False)._run_sync(_req())

    assert len(model.calls) == 1
    assert result.retried is False


def test_second_attempt_is_returned_even_if_also_degenerate():
    """One retry, not a loop — a persistently bad prompt must still terminate."""
    model = _FakeModel([[_mostly_silent()], [_mostly_silent()]])
    result = _service(model)._run_sync(_req())

    assert len(model.calls) == 2
    assert result.retried is True


def test_retry_preserves_every_other_parameter():
    model = _FakeModel([[_mostly_silent()], [_speech_like()]])
    _service(model)._run_sync(_req(speed=1.5, guidance_scale=3.0, num_step=12))

    first, second = model.calls
    for key in ("speed", "guidance_scale", "num_step", "text", "denoise", "t_shift"):
        assert first[key] == second[key], f"{key} changed across the retry"


# ── Seeding ──────────────────────────────────────────────────────────────────


def test_same_seed_produces_identical_rng_draws():
    """The seed must be applied to torch's RNG immediately before generation."""
    draws = []

    class RecordingModel(_FakeModel):
        def generate(self, **kwargs):
            draws.append(torch.randn(4).tolist())
            return [_speech_like()]

    svc = _service(RecordingModel([]))
    svc._run_sync(_req(seed=1234))
    svc._run_sync(_req(seed=1234))
    svc._run_sync(_req(seed=9999))

    assert draws[0] == draws[1]
    assert draws[0] != draws[2]


def test_request_seed_overrides_server_default():
    draws = []

    class RecordingModel(_FakeModel):
        def generate(self, **kwargs):
            draws.append(torch.randn(4).tolist())
            return [_speech_like()]

    svc_default = _service(RecordingModel([]), seed=1234)
    svc_default._run_sync(_req())
    svc_default._run_sync(_req(seed=1234))

    assert draws[0] == draws[1]


def test_unseeded_requests_stay_random():
    draws = []

    class RecordingModel(_FakeModel):
        def generate(self, **kwargs):
            draws.append(torch.randn(4).tolist())
            return [_speech_like()]

    svc = _service(RecordingModel([]))
    svc._run_sync(_req())
    svc._run_sync(_req())

    assert draws[0] != draws[1]


# ── Router plumbing ──────────────────────────────────────────────────────────


def test_seed_reaches_the_synthesis_request(client):
    resp = client.post("/v1/audio/speech", json={"input": "Hello", "seed": 42})
    assert resp.status_code == 200
    assert client.app.state.inference_svc.synthesize.await_args.args[0].seed == 42


def test_seed_defaults_to_none(client):
    resp = client.post("/v1/audio/speech", json={"input": "Hello"})
    assert resp.status_code == 200
    assert client.app.state.inference_svc.synthesize.await_args.args[0].seed is None


@pytest.mark.parametrize("bad_seed", [-1, 2**32])
def test_out_of_range_seed_is_rejected(client, bad_seed):
    resp = client.post("/v1/audio/speech", json={"input": "Hello", "seed": bad_seed})
    assert resp.status_code == 422


def test_streamed_chunks_inherit_the_seed(client):
    """
    _chunk_request must carry every parameter forward. It used to rebuild the
    request field by field, which silently dropped anything newly added.
    """
    from omnivoice_server.routers.speech import _chunk_request

    base = _req(seed=7, speed=1.25, language="en")
    chunk = _chunk_request("One sentence.", base)

    assert chunk.text == "One sentence."
    assert chunk.seed == 7
    assert chunk.speed == 1.25
    assert chunk.language == "en"


def test_unknown_tags_are_surfaced_in_a_response_header(client):
    resp = client.post("/v1/audio/speech", json={"input": "Hi [laugh] there"})
    assert resp.status_code == 200
    assert resp.headers["X-Unknown-Nonverbal-Tags"] == "laugh"


def test_known_tags_produce_no_warning_header(client):
    resp = client.post("/v1/audio/speech", json={"input": "Hi [laughter] there"})
    assert resp.status_code == 200
    assert "X-Unknown-Nonverbal-Tags" not in resp.headers


# ── Empty generations ────────────────────────────────────────────────────────


def test_zero_length_output_does_not_crash():
    """
    The RTF log line divides by duration. Its f-string was built regardless of
    log level, so an empty generation raised ZeroDivisionError and reached the
    client as a 500 — a crash caused by the logging, not by the empty audio.
    """
    model = _FakeModel([[torch.zeros(1, 0)]])
    result = _service(model)._run_sync(_req())

    assert result.duration_s == 0
    assert result.tensors is not None


def test_empty_tensor_list_does_not_crash():
    model = _FakeModel([[]])
    result = _service(model)._run_sync(_req())

    assert result.duration_s == 0
