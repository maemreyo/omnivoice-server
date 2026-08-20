"""
Tests for health and metrics endpoints.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from omnivoice_server.app import create_app


@pytest.fixture
def client_not_loaded(settings):
    """Client where model is NOT loaded (is_loaded=False)."""
    app = create_app(settings)

    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: False),
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


def test_health_model_not_loaded(client_not_loaded):
    """GET /health returns 503 with status=starting and ready=False when model is loading."""
    resp = client_not_loaded.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "starting"
    assert data["ready"] is False
    assert data["model_loaded"] is False


def test_health_model_loaded(client):
    """GET /health returns 200 with status=healthy, ready=True, and model_id."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["ready"] is True
    assert data["model_loaded"] is True
    assert "model_id" in data
    assert "uptime_s" in data
    assert "memory_rss_mb" in data


def test_metrics_ok(client):
    """GET /metrics returns 200 with requests_total, ram_mb."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "requests_total" in data
    assert "streaming_requests_total" in data
    assert "streaming_ttfa_ms_mean" in data
    assert "streaming_first_clone_prompt_ms_mean" in data
    assert "streaming_first_decode_postprocess_ms_mean" in data
    assert "streaming_first_cleanup_ms_mean" in data
    assert "streaming_latest" in data
    assert "ram_mb" in data
    assert "cuda_alloc_conf" in data
    assert "cuda_allocated_mb" in data
    assert "cuda_reserved_mb" in data
    assert "cuda_non_torch_mb_estimate" in data
    assert "model_audio_tokenizer_params_mb" in data
    assert "prompt_cache_entries" in data
