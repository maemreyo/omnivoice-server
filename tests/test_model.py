"""Tests for model service utilities."""

from __future__ import annotations

import numpy as np
import torch

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
