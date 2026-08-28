"""
End-to-end behaviour of .txt voice files through the HTTP API (issue #38).

The point of the feature is that an OpenAI-compatible client — which can only
send a bare `voice` string — can select a voice design. These tests exercise it
the way such a client would.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client_with_voices(voice_dir, settings):
    """A client whose voice directory already contains two voice files."""
    (voice_dir / "canadian-lady.txt").write_text(
        "# what my podcast app should use\nfemale, young adult, canadian accent\nseed: 4242\n"
    )
    (voice_dir / "narrator.txt").write_text(
        "description: Audiobook narration\nmale, middle-aged, low pitch, british accent\n"
    )

    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from omnivoice_server.app import create_app
    from tests.conftest import _mock_synthesize

    app = create_app(settings)
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with patch(
            "omnivoice_server.services.model.ModelService.is_loaded",
            new_callable=lambda: property(lambda self: True),
        ):
            with TestClient(app) as c:
                c.app.state.inference_svc.synthesize = AsyncMock(side_effect=_mock_synthesize)
                yield c


def _last_request(client):
    return client.app.state.inference_svc.synthesize.await_args.args[0]


def test_bare_filename_selects_the_voice_design(client_with_voices):
    """The whole point: no `instructions` field needed."""
    resp = client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hello", "voice": "canadian-lady"}
    )
    assert resp.status_code == 200

    req = _last_request(client_with_voices)
    assert req.mode == "design"
    assert "canadian accent" in req.instruct


def test_voice_file_params_are_applied(client_with_voices):
    client_with_voices.post("/v1/audio/speech", json={"input": "Hi", "voice": "canadian-lady"})
    assert _last_request(client_with_voices).seed == 4242


def test_request_parameters_beat_the_voice_file(client_with_voices):
    """A file names a voice; it does not overrule the caller."""
    client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hi", "voice": "canadian-lady", "seed": 1}
    )
    assert _last_request(client_with_voices).seed == 1


def test_explicit_value_equal_to_the_default_still_beats_the_file(client_with_voices):
    """
    speed defaults to 1.0, so comparing against defaults cannot tell an omitted
    field from one explicitly set to the same value.
    """
    (client_with_voices.app.state.cfg.voice_dir / "slow.txt").write_text(
        "female, british accent\nspeed: 0.5\n"
    )
    client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hi", "voice": "slow", "speed": 1.0}
    )
    assert _last_request(client_with_voices).speed == 1.0


def test_voice_file_works_through_the_speaker_field_too(client_with_voices):
    resp = client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hello", "speaker": "narrator"}
    )
    assert resp.status_code == 200
    assert "british accent" in _last_request(client_with_voices).instruct


def test_unknown_voice_is_still_rejected(client_with_voices):
    resp = client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hello", "voice": "no-such-voice"}
    )
    assert resp.status_code == 422


def test_voice_files_appear_in_the_voices_listing(client_with_voices):
    resp = client_with_voices.get("/v1/voices")
    assert resp.status_code == 200

    by_id = {v["id"]: v for v in resp.json()["voices"]}
    assert by_id["canadian-lady"]["type"] == "file"
    assert by_id["canadian-lady"]["params"] == {"seed": 4242}
    assert by_id["narrator"]["description"] == "Audiobook narration"


def test_listing_total_counts_voice_files(client_with_voices):
    body = client_with_voices.get("/v1/voices").json()
    assert body["total"] == len(body["voices"])


def test_a_voice_file_shadows_a_built_in_preset(client_with_voices):
    """User configuration beats a built-in heuristic mapping of the same name."""
    (client_with_voices.app.state.cfg.voice_dir / "nova.txt").write_text(
        "male, elderly, very low pitch, russian accent\n"
    )
    client_with_voices.post("/v1/audio/speech", json={"input": "Hi", "voice": "nova"})
    assert "russian accent" in _last_request(client_with_voices).instruct


def test_broken_voice_file_does_not_break_the_listing(client_with_voices):
    (client_with_voices.app.state.cfg.voice_dir / "broken.txt").write_text("cheerful, excited")
    resp = client_with_voices.get("/v1/voices")
    assert resp.status_code == 200
    assert "broken" not in {v["id"] for v in resp.json()["voices"]}


def test_broken_voice_file_is_not_selectable(client_with_voices):
    (client_with_voices.app.state.cfg.voice_dir / "broken.txt").write_text("cheerful, excited")
    resp = client_with_voices.post("/v1/audio/speech", json={"input": "Hi", "voice": "broken"})
    assert resp.status_code == 422


def test_clone_prefix_still_takes_its_own_path(client_with_voices):
    """`clone:` must not be swallowed by voice-file lookup."""
    resp = client_with_voices.post(
        "/v1/audio/speech", json={"input": "Hi", "voice": "clone:missing"}
    )
    assert resp.status_code == 404


def test_auto_is_reserved_and_not_overridable_by_a_file(client_with_voices):
    (client_with_voices.app.state.cfg.voice_dir / "auto.txt").write_text(
        "male, elderly, indian accent\n"
    )
    client_with_voices.post("/v1/audio/speech", json={"input": "Hi", "voice": "auto"})
    assert "indian accent" not in _last_request(client_with_voices).instruct
