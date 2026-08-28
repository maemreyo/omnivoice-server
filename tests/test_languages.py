"""
Language discovery and validation.

Upstream accepts several hundred languages by ID or full name, and treats an
unrecognised value as a log warning plus a silent fall back to
language-agnostic synthesis. Neither the list nor the failure was visible
through the API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from omnivoice_server.app import create_app

FAKE_IDS = {"en", "vi", "zh"}
FAKE_NAMES = {"english", "vietnamese", "chinese"}


class _FakeModel:
    supported_language_ids = FAKE_IDS
    supported_language_names = FAKE_NAMES


@pytest.fixture
def lang_client(settings):
    """A client whose model reports a small, known language set."""
    from tests.conftest import _mock_synthesize

    app = create_app(settings)
    with (
        patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock),
        patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: True),
        ),
        patch(
            "omnivoice_server.services.model.ModelService.model",
            new_callable=lambda: property(lambda self: _FakeModel()),
        ),
        TestClient(app) as client,
    ):
        client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_mock_synthesize)
        yield client


# ── Discovery ────────────────────────────────────────────────────────────────


def test_languages_are_listed(lang_client):
    body = lang_client.get("/v1/languages").json()
    assert body["ids"] == sorted(FAKE_IDS)
    assert body["names"] == sorted(FAKE_NAMES)
    assert body["total"] == len(FAKE_IDS)


def test_language_list_is_sorted(lang_client):
    ids = lang_client.get("/v1/languages").json()["ids"]
    assert ids == sorted(ids)


def test_languages_503_while_the_model_loads(settings):
    app = create_app(settings)
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with TestClient(app) as client:
            assert client.get("/v1/languages").status_code == 503


# ── Validation ───────────────────────────────────────────────────────────────


def test_known_language_id_is_accepted(lang_client):
    resp = lang_client.post("/v1/audio/speech", json={"input": "Hello", "language": "vi"})
    assert resp.status_code == 200


def test_known_language_name_is_accepted(lang_client):
    resp = lang_client.post("/v1/audio/speech", json={"input": "Hello", "language": "vietnamese"})
    assert resp.status_code == 200


def test_language_matching_is_case_insensitive(lang_client):
    resp = lang_client.post("/v1/audio/speech", json={"input": "Hello", "language": "VI"})
    assert resp.status_code == 200


def test_unknown_language_is_rejected(lang_client):
    """
    Upstream would accept this and quietly synthesize language-agnostic audio,
    leaving the caller with a subtly wrong voice and nothing to explain it.
    """
    resp = lang_client.post("/v1/audio/speech", json={"input": "Hello", "language": "klingon"})
    assert resp.status_code == 422

    # The app reshapes HTTPException into {"error": {"code", "message"}}.
    message = resp.json()["error"]["message"]
    assert "klingon" in message
    assert "/v1/languages" in message, "the error should say where the list is"


def test_omitting_language_is_still_allowed(lang_client):
    resp = lang_client.post("/v1/audio/speech", json={"input": "Hello"})
    assert resp.status_code == 200
    assert lang_client.app.state.inference_svc.synthesize.await_args.args[0].language is None


def test_clone_endpoint_validates_language_too(lang_client, sample_audio_bytes):
    resp = lang_client.post(
        "/v1/audio/speech/clone",
        data={"text": "Hello", "language": "klingon"},
        files={"ref_audio": ("ref.wav", sample_audio_bytes, "audio/wav")},
    )
    assert resp.status_code == 422


def test_validation_is_skipped_while_the_model_is_unloaded(settings):
    """Rejecting on an empty list would refuse every language during startup."""
    from omnivoice_server.services.model import ModelService

    svc = ModelService(settings)
    assert svc.accepts_language("anything") is True
