"""Tests for model service utilities."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import torch
from torch import nn

from omnivoice_server.services.model import ModelService


def test_modelservice_has_nan_handles_numpy_array_direct():
    arr = np.array([0.0, 1.0, np.nan], dtype=np.float32)
    assert ModelService._has_nan(arr) is True


def test_modelservice_has_nan_handles_numpy_array_in_list():
    arr = np.array([0.0, 1.0, np.nan], dtype=np.float32)
    assert ModelService._has_nan([arr]) is True


def test_modelservice_has_nan_handles_nested_numpy_collections():
    arr = np.array([0.0, 1.0], dtype=np.float32)
    assert ModelService._has_nan([[arr, arr]]) is False


def test_modelservice_has_nan_handles_torch_tensor_with_nan():
    t = torch.tensor([0.0, float("nan"), 1.0])
    assert ModelService._has_nan(t) is True


def test_modelservice_has_nan_handles_torch_tensor_without_nan():
    t = torch.tensor([0.0, 1.0, 2.0])
    assert ModelService._has_nan(t) is False


def test_remember_audio_tokenizer_device_uses_decoder_projection():
    class HeterogeneousTokenizer(nn.Module):
        def __init__(self):
            super().__init__()
            self.semantic_model = nn.Linear(1, 1, device="meta")
            self.fc2 = nn.Linear(1, 1, device="cpu")

    model = SimpleNamespace(audio_tokenizer=HeterogeneousTokenizer())

    ModelService._remember_audio_tokenizer_device(model)

    assert model._omnivoice_server_audio_tokenizer_device == torch.device("cpu")


def test_audio_tokenizer_decode_moves_codes_to_remembered_device(monkeypatch):
    class FakeCodes:
        def __init__(self):
            self.moved_to = None

        def to(self, device):
            self.moved_to = device
            return self

    codes = FakeCodes()
    model = SimpleNamespace(
        _omnivoice_server_audio_tokenizer_device=torch.device("cuda", 0)
    )
    received = []

    monkeypatch.setattr(torch, "is_tensor", lambda value: value is codes)
    wrapped = ModelService._wrap_audio_tokenizer_decode(received.append, model)

    wrapped(codes)

    assert codes.moved_to == torch.device("cuda", 0)
    assert received == [codes]
