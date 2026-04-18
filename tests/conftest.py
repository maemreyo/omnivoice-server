"""
Shared fixtures for all tests.

FIX: settings() fixture previously used pytest.tmp_path_factory.mktemp()
as a plain attribute call — this is not valid Python. tmp_path_factory must
be declared as a fixture parameter. Fixed below.
"""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, patch

import pytest
import torch
from fastapi.testclient import TestClient

from omnivoice_server.app import create_app
from omnivoice_server.config import Settings

# ── Audio helpers ─────────────────────────────────────────────────────────────


def make_silence_tensor(duration_s: float = 1.0) -> torch.Tensor:
    """Return a silent (1, T) float32 tensor at 24kHz."""
    num_samples = int(24_000 * duration_s)
    return torch.zeros(1, num_samples)


def make_wav_bytes(duration_frames: int = 0, sample_rate: int = 24000) -> bytes:
    """
    Minimal valid WAV file. Used by clone and profile tests.
    duration_frames=0 gives the smallest valid WAV (44-byte header, no audio).
    Tests that need parseable audio should pass duration_frames > 0.
    """
    data_size = duration_frames * 2  # 16-bit mono
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", data_size)
        + b"\x00" * data_size
    )


# ── Mock inference ────────────────────────────────────────────────────────────


def _mock_synthesize(req, **_kwargs):
    """Fake synthesis — returns 1s of silence immediately."""
    from omnivoice_server.services.inference import SynthesisResult

    tensor = make_silence_tensor(1.0)
    return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def settings(tmp_path_factory):  # FIX: tmp_path_factory is a fixture param, not pytest attr
    profile_dir = tmp_path_factory.mktemp("profiles")
    return Settings(
        device="cpu",
        num_step=4,
        max_concurrent=1,
        api_key="",
        profile_dir=profile_dir,
    )


@pytest.fixture
def client(settings):
    app = create_app(settings)

    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: True),
        ):
            with TestClient(app) as c:
                c.app.state.inference_svc.synthesize = AsyncMock(side_effect=_mock_synthesize)
                yield c


@pytest.fixture
def sample_audio_bytes():
    """A minimal WAV suitable for upload tests."""
    return make_wav_bytes(duration_frames=100)
