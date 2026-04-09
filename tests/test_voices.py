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


def test_list_voices_design_attributes_match_omnivoice_validator(client):
    """Exposed design attributes should match the installed OmniVoice vocabulary."""
    resp = client.get("/v1/voices")
    assert resp.status_code == 200

    design_attributes = resp.json()["design_attributes"]
    assert design_attributes["age"] == [
        "child",
        "teenager",
        "young adult",
        "middle-aged",
        "elderly",
    ]
    assert design_attributes["pitch"] == [
        "very low pitch",
        "low pitch",
        "moderate pitch",
        "high pitch",
        "very high pitch",
    ]
    assert design_attributes["accent_en"] == [
        "american accent",
        "british accent",
        "australian accent",
        "chinese accent",
        "canadian accent",
        "indian accent",
        "korean accent",
        "portuguese accent",
        "russian accent",
        "japanese accent",
    ]
    assert design_attributes["dialect_zh"] == [
        "河南话",
        "陕西话",
        "四川话",
        "贵州话",
        "云南话",
        "桂林话",
        "济南话",
        "石家庄话",
        "甘肃话",
        "宁夏话",
        "青岛话",
        "东北话",
    ]


def test_list_voices_includes_openai_presets(client):
    """GET /v1/voices should advertise OpenAI-compatible preset names."""
    resp = client.get("/v1/voices")
    assert resp.status_code == 200

    ids = [voice["id"] for voice in resp.json()["voices"]]
    for preset_name in ("alloy", "nova", "onyx", "shimmer", "verse", "cedar", "marin"):
        assert preset_name in ids


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
    """Saved profiles do not affect /v1/audio/speech when voice is ignored."""
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
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
