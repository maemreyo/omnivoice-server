"""
Tests for voice profile management endpoints.
"""

from __future__ import annotations

import io


def test_list_voices_empty(client):
    """GET /v1/voices returns voices list."""
    resp = client.get("/v1/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert "voices" in data
    # At minimum: auto + design placeholder
    assert len(data["voices"]) >= 2


def test_create_and_list_profile(client, sample_audio_bytes):
    """POST creates profile, appears in list."""
    # Create
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "test-voice", "ref_text": "Hello world"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 201
    assert resp.json()["profile_id"] == "test-voice"

    # Appears in list
    resp = client.get("/v1/voices")
    ids = [v["profile_id"] for v in resp.json()["voices"] if "profile_id" in v]
    assert "test-voice" in ids


def test_create_profile_duplicate_rejected(client, sample_audio_bytes):
    """Duplicate returns 409."""
    for _ in range(2):
        resp = client.post(
            "/v1/voices/profiles",
            data={"profile_id": "dup"},
            files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
        )
    assert resp.status_code == 409


def test_delete_profile(client, sample_audio_bytes):
    """DELETE returns 204."""
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "to-delete"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    resp = client.delete("/v1/voices/profiles/to-delete")
    assert resp.status_code == 204


def test_invalid_profile_id_rejected(client, sample_audio_bytes):
    """Invalid ID returns 422."""
    resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "has spaces"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 422


def test_speech_with_saved_profile(client, sample_audio_bytes):
    """Use saved profile in speech endpoint."""
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "myvoice"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    resp = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello with cloned voice",
            "voice": "clone:myvoice",
        },
    )
    assert resp.status_code == 200


def test_profile_mutations_invalidate_prompt_cache(client, sample_audio_bytes, monkeypatch):
    import io

    invalidated: list[str] = []

    def fake_invalidate(profile_id: str | None = None) -> None:
        invalidated.append(profile_id or "<all>")

    monkeypatch.setattr(
        client.app.state.model_svc,
        "invalidate_voice_clone_prompt",
        fake_invalidate,
    )

    create_resp = client.post(
        "/v1/voices/profiles",
        data={"profile_id": "cache-me", "ref_text": "first"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert create_resp.status_code == 201

    update_resp = client.patch(
        "/v1/voices/profiles/cache-me",
        data={"ref_text": "updated"},
    )
    assert update_resp.status_code == 200

    delete_resp = client.delete("/v1/voices/profiles/cache-me")
    assert delete_resp.status_code == 204

    assert invalidated == ["cache-me", "cache-me", "cache-me"]
