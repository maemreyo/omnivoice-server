"""
The optional browser UI (issue #36).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from omnivoice_server.app import create_app
from omnivoice_server.config import Settings


def _client(settings):
    app = create_app(settings)
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: True),
        ):
            with TestClient(app) as c:
                yield c


@pytest.fixture
def ui_client(settings):
    yield from _client(settings)


@pytest.fixture
def no_ui_client(tmp_path_factory, voice_dir):
    settings = Settings(
        device="cpu",
        num_step=4,
        max_concurrent=1,
        api_key="",
        profile_dir=tmp_path_factory.mktemp("profiles"),
        voice_dir=voice_dir,
        web_ui=False,
    )
    yield from _client(settings)


def test_ui_is_served_by_default(ui_client):
    resp = ui_client.get("/ui")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "OmniVoice Server" in resp.text


def test_root_redirects_to_the_ui(ui_client):
    resp = ui_client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/ui"


def test_ui_is_self_contained(ui_client):
    """
    No external assets: a local TTS server is routinely run offline, and a page
    that needs a CDN would simply not render there.
    """
    body = ui_client.get("/ui").text
    for external in ("<script src=", "<link rel=\"stylesheet\"", "@import", "<img src=\"http"):
        assert external not in body, f"page pulls an external asset: {external}"


def test_ui_can_be_disabled(no_ui_client):
    assert no_ui_client.get("/ui").status_code == 404


def test_root_is_untouched_when_ui_is_disabled(no_ui_client):
    """Disabling the UI must not leave a redirect behind on /."""
    assert no_ui_client.get("/", follow_redirects=False).status_code == 404


def test_api_still_works_with_the_ui_disabled(no_ui_client):
    assert no_ui_client.get("/health").status_code == 200


def test_ui_is_excluded_from_the_openapi_schema(ui_client):
    paths = ui_client.get("/openapi.json").json()["paths"]
    assert "/ui" not in paths
    assert "/" not in paths


# ── Auth interaction ─────────────────────────────────────────────────────────


@pytest.fixture
def authed_client(tmp_path_factory, voice_dir):
    settings = Settings(
        device="cpu",
        num_step=4,
        max_concurrent=1,
        api_key="secret-key",
        profile_dir=tmp_path_factory.mktemp("profiles"),
        voice_dir=voice_dir,
    )
    yield from _client(settings)


def test_ui_page_loads_without_a_key(authed_client):
    """Otherwise there is nowhere to type the key."""
    assert authed_client.get("/ui").status_code == 200


def test_api_still_requires_the_key_when_the_ui_is_open(authed_client):
    """Exempting the page must not exempt the endpoints it calls."""
    assert authed_client.get("/v1/voices").status_code == 401
    assert authed_client.post("/v1/audio/speech", json={"input": "hi"}).status_code == 401


def test_api_accepts_the_key_as_normal(authed_client):
    resp = authed_client.get("/v1/voices", headers={"Authorization": "Bearer secret-key"})
    assert resp.status_code == 200
