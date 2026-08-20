from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from omnivoice_server.app import create_app
from omnivoice_server.config import Settings
from omnivoice_server.services.inference import SynthesisResult


def _mock_synthesize(req, **_kwargs):
    tensor = __import__("torch").zeros(1, 24_000)
    return SynthesisResult(tensors=[tensor], duration_s=1.0, latency_s=0.05)


def _make_client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: True),
        ):
            client = TestClient(app)
            client.__enter__()
            client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_mock_synthesize)
            return client


def _base_settings(tmp_path, **overrides) -> Settings:
    values = {
        "device": "cpu",
        "num_step": 4,
        "max_concurrent": 1,
        "api_key": "",
        "profile_dir": tmp_path / "profiles",
        "cors_allow_origins": ["http://localhost:5001"],
    }
    values.update(overrides)
    return Settings(
        **values,
    )


def test_cors_preflight_allows_configured_origin(tmp_path):
    settings = _base_settings(tmp_path)

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5001"
    assert "POST" in resp.headers["access-control-allow-methods"]


def test_cors_preflight_bypasses_auth_for_options(tmp_path):
    settings = _base_settings(tmp_path, api_key="secret-token")

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5001"


def test_cors_simple_response_exposes_audio_headers(tmp_path):
    settings = _base_settings(tmp_path)

    with _make_client(settings) as client:
        resp = client.post(
            "/v1/audio/speech",
            json={"model": "omnivoice", "input": "Hello world", "voice": "auto"},
            headers={"Origin": "http://localhost:5001"},
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5001"
    exposed_headers = resp.headers["access-control-expose-headers"]
    assert "X-Audio-Duration-S" in exposed_headers
    assert "X-Synthesis-Latency-S" in exposed_headers


def test_cors_preflight_rejects_disallowed_origin(tmp_path):
    settings = _base_settings(tmp_path, cors_allow_origins=["http://localhost:3000"])

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_simple_request_from_disallowed_origin_has_no_allow_origin_header(tmp_path):
    settings = _base_settings(tmp_path, cors_allow_origins=["http://localhost:3000"])

    with _make_client(settings) as client:
        resp = client.post(
            "/v1/audio/speech",
            json={"model": "omnivoice", "input": "Hello world", "voice": "auto"},
            headers={"Origin": "http://localhost:5001"},
        )

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_cors_preflight_includes_requested_headers(tmp_path):
    settings = _base_settings(tmp_path)

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )

    assert resp.status_code == 200
    allow_headers = resp.headers["access-control-allow-headers"].lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers


def test_non_cors_options_request_still_hits_auth_when_api_key_enabled(tmp_path):
    settings = _base_settings(tmp_path, api_key="secret-token")

    with _make_client(settings) as client:
        resp = client.options("/v1/audio/speech")

    assert resp.status_code == 405


def test_post_without_api_key_is_rejected_even_when_origin_allowed(tmp_path):
    settings = _base_settings(tmp_path, api_key="secret-token")

    with _make_client(settings) as client:
        resp = client.post(
            "/v1/audio/speech",
            json={"model": "omnivoice", "input": "Hello world", "voice": "auto"},
            headers={"Origin": "http://localhost:5001"},
        )

    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5001"


def test_post_with_api_key_and_allowed_origin_succeeds(tmp_path):
    settings = _base_settings(tmp_path, api_key="secret-token")

    with _make_client(settings) as client:
        resp = client.post(
            "/v1/audio/speech",
            json={"model": "omnivoice", "input": "Hello world", "voice": "auto"},
            headers={
                "Origin": "http://localhost:5001",
                "Authorization": "Bearer secret-token",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5001"


def test_credentials_true_with_wildcard_origin_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="cors_allow_credentials"):
        _base_settings(
            tmp_path,
            cors_allow_origins=["*"],
            cors_allow_credentials=True,
        )


def test_cors_origins_parse_from_comma_separated_string(tmp_path):
    settings = _base_settings(
        tmp_path,
        cors_allow_origins="http://localhost:5001, http://127.0.0.1:5173",
    )

    assert settings.cors_allow_origins == [
        "http://localhost:5001",
        "http://127.0.0.1:5173",
    ]


def test_cors_origins_parse_from_json_string(tmp_path):
    settings = _base_settings(
        tmp_path,
        cors_allow_origins='["http://localhost:5001", "http://127.0.0.1:5173"]',
    )

    assert settings.cors_allow_origins == [
        "http://localhost:5001",
        "http://127.0.0.1:5173",
    ]


def test_empty_cors_origin_string_disables_cors_headers(tmp_path):
    settings = _base_settings(tmp_path, cors_allow_origins="")

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 405
    assert "access-control-allow-origin" not in resp.headers


def test_wildcard_origin_without_credentials_returns_wildcard_header(tmp_path):
    settings = _base_settings(tmp_path, cors_allow_origins=["*"], cors_allow_credentials=False)

    with _make_client(settings) as client:
        resp = client.options(
            "/v1/audio/speech",
            headers={
                "Origin": "http://localhost:5001",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
