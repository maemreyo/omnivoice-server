"""Compatibility tests for the faster-qwen3-tts API surface."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
from unittest.mock import AsyncMock, patch

from omnivoice_server.services.profiles import ProfileNotFoundError, ProfileService


def _upload(client, sample_audio_bytes, name="uploaded"):
    return client.post(
        "/upload_voice",
        data={"name": name, "ref_text": "Reference text"},
        files={"voice_file": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )


def test_compat_model_and_voice_aliases(client):
    models = client.get("/v1/audio/models")
    assert models.status_code == 200
    assert models.json()["object"] == "list"

    voices = client.get("/v1/audio/voices")
    assert voices.status_code == 200
    assert voices.json()["object"] == "list"
    assert any(item["id"] == "alloy" for item in voices.json()["data"])


def test_upload_voice_and_crud_compatibility(client, sample_audio_bytes):
    created = _upload(client, sample_audio_bytes)
    assert created.status_code == 200
    voice_id = created.json()["voice_id"]

    fetched = client.get(f"/v1/audio/voices/{voice_id}")
    assert fetched.status_code == 200
    assert fetched.json()["voice_id"] == voice_id
    assert fetched.json()["name"] == "uploaded"

    updated = client.patch(
        f"/v1/audio/voices/{voice_id}",
        json={"name": "renamed", "ref_text": "Updated reference"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["ref_text"] == "Updated reference"

    by_name = client.get("/v1/audio/voices/renamed")
    assert by_name.status_code == 200
    assert by_name.json()["voice_id"] == voice_id

    deleted = client.delete(f"/v1/audio/voices/{voice_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/v1/audio/voices/{voice_id}").status_code == 404


def test_speech_accepts_faster_qwen_request_aliases(client, sample_audio_bytes):
    created = _upload(client, sample_audio_bytes, name="alias-voice")
    assert created.status_code == 200

    response = client.post(
        "/v1/audio/speech",
        json={
            "model": "tts-1",
            "input": "Hello compatibility.",
            "voice": "alias-voice",
            "reference_text": "Override reference",
            "stream": False,
            "response_format": "wav",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")


def test_reference_text_takes_compatibility_precedence(client, sample_audio_bytes):
    created = _upload(client, sample_audio_bytes, name="precedence-voice")
    assert created.status_code == 200
    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "Alias precedence.",
            "voice": "precedence-voice",
            "reference_text": "preferred",
            "ref_text": "fallback",
        },
    )
    assert response.status_code == 200
    request = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert request.ref_text == "preferred"


def test_profile_patch_preserves_compatibility_metadata(client, sample_audio_bytes):
    created = _upload(client, sample_audio_bytes, name="persistent-name")
    voice_id = created.json()["voice_id"]
    before = client.get(f"/v1/audio/voices/{voice_id}").json()

    response = client.patch(
        f"/v1/voices/profiles/{voice_id}",
        data={"ref_text": "replacement transcript"},
    )
    assert response.status_code == 200
    after = client.get(f"/v1/audio/voices/{voice_id}").json()
    assert after["name"] == "persistent-name"
    assert after["ref_text"] == "replacement transcript"
    assert after["created"] == before["created"]


def test_audio_only_profile_patch_preserves_transcript(client, sample_audio_bytes):
    created = _upload(client, sample_audio_bytes, name="audio-update")
    voice_id = created.json()["voice_id"]
    response = client.patch(
        f"/v1/voices/profiles/{voice_id}",
        files={"ref_audio": ("replacement.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert response.status_code == 200
    voice = client.get(f"/v1/audio/voices/{voice_id}").json()
    assert voice["name"] == "audio-update"
    assert voice["ref_text"] == "Reference text"


def test_sse_stream_format_emits_audio_events(client):
    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "Hello SSE.",
            "voice": "alloy",
            "stream": True,
            "stream_format": "sse",
            "response_format": "pcm",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    audio_event = json.loads(events[0])
    assert audio_event["type"] == "audio.chunk"
    assert base64.b64decode(audio_event["data"])
    assert json.loads(events[-2])["type"] == "done"


def test_sse_stream_format_enables_streaming_without_stream_flag(client):
    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "Implicit SSE streaming.",
            "stream_format": "sse",
            "response_format": "pcm",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text


def test_sse_and_response_formats_are_case_insensitive(client):
    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "Uppercase formats.",
            "stream_format": "SSE",
            "response_format": "WAV",
        },
    )
    assert response.status_code == 200
    first_event = next(
        line[6:] for line in response.text.splitlines() if line.startswith("data: {")
    )
    payload = json.loads(first_event)
    wav = base64.b64decode(payload["data"])
    assert wav.startswith(b"RIFF")
    assert struct.unpack("<I", wav[4:8])[0] == len(wav) - 8
    assert struct.unpack("<I", wav[40:44])[0] == len(wav) - 44


def test_wav_stream_has_compatibility_header(client):
    response = client.post(
        "/v1/audio/speech",
        json={"input": "Hello WAV.", "stream": True, "response_format": "wav"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")


def test_upload_rejects_non_object_metadata(client, sample_audio_bytes):
    response = client.post(
        "/upload_voice",
        data={"data": "[]"},
        files={"voice_file": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert response.status_code == 400
    assert "JSON object" in response.text


def test_upload_rejects_duplicate_display_name(client, sample_audio_bytes):
    assert _upload(client, sample_audio_bytes, name="duplicate").status_code == 200
    response = _upload(client, sample_audio_bytes, name="DUPLICATE")
    assert response.status_code == 409


def test_profile_alias_does_not_sanitize_to_an_existing_id(tmp_path, sample_audio_bytes):
    profiles = ProfileService(tmp_path)
    profiles.save_profile("voice", sample_audio_bytes)
    try:
        profiles.resolve_profile_id("voice!")
    except ProfileNotFoundError:
        pass
    else:
        raise AssertionError("invalid alias unexpectedly resolved to a sanitized profile ID")


def test_legacy_duplicate_profile_alias_is_rejected(tmp_path, sample_audio_bytes):
    profiles = ProfileService(tmp_path)
    profiles.save_profile("first", sample_audio_bytes)
    profiles.save_profile("second", sample_audio_bytes)
    profiles.update_metadata("first", name="duplicate", update_name=True)
    profiles.update_metadata("second", name="duplicate", update_name=True)

    try:
        profiles.resolve_profile_id("duplicate")
    except ValueError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous legacy alias unexpectedly resolved")


def test_failed_new_profile_write_does_not_leave_orphan(tmp_path, sample_audio_bytes, monkeypatch):
    profiles = ProfileService(tmp_path)
    original_write = profiles._write_atomic

    def fail_metadata(path, data):
        if path.name == "meta.json":
            raise OSError("simulated metadata failure")
        original_write(path, data)

    monkeypatch.setattr(profiles, "_write_atomic", fail_metadata)
    try:
        profiles.save_profile("incomplete", sample_audio_bytes)
    except OSError:
        pass
    else:
        raise AssertionError("simulated profile write unexpectedly succeeded")
    assert not (tmp_path / "incomplete").exists()


def test_ambiguous_legacy_profile_alias_returns_conflict(client, sample_audio_bytes):
    profiles = client.app.state.profile_svc
    profiles.save_profile("first", sample_audio_bytes)
    profiles.save_profile("second", sample_audio_bytes)
    profiles.update_metadata("first", name="duplicate", update_name=True)
    profiles.update_metadata("second", name="duplicate", update_name=True)

    assert client.get("/v1/audio/voices/duplicate").status_code == 409
    response = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "voice": "duplicate"},
    )
    assert response.status_code == 409


def test_uppercase_clone_prefix_uses_profile_cache(client, sample_audio_bytes):
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "cached"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    response = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "voice": "Clone:cached", "response_format": "wav"},
    )
    assert response.status_code == 200
    request = client.app.state.inference_svc.synthesize.await_args.args[0]
    assert request.profile_id == "cached"


def test_invalid_stream_format_is_rejected(client):
    response = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream_format": "ndjson"},
    )
    assert response.status_code == 422


def test_blank_speech_input_is_rejected_before_inference(client):
    client.app.state.inference_svc.synthesize.reset_mock()
    response = client.post("/v1/audio/speech", json={"input": "   \n"})
    assert response.status_code == 422
    client.app.state.inference_svc.synthesize.assert_not_awaited()


def test_missing_clone_profile_error_names_real_creation_endpoint(client):
    response = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "voice": "clone:missing"},
    )
    assert response.status_code == 404
    assert "/v1/voices/profiles" in response.text


def test_invalid_stream_request_does_not_download_voice_url(client):
    download = AsyncMock()
    with patch("omnivoice_server.routers.speech._download_voice_url", download):
        response = client.post(
            "/v1/audio/speech",
            json={
                "input": "Hello.",
                "stream": True,
                "response_format": "mp3",
                "voice_url": "https://example.com/ref.wav",
            },
        )
    assert response.status_code == 400
    download.assert_not_awaited()


def test_oversized_voice_url_removes_partial_temp_file(tmp_path, monkeypatch):
    from omnivoice_server.routers import speech

    output_path = tmp_path / "partial.wav"

    class Response:
        headers = {}

        def __init__(self):
            self.reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            self.reads += 1
            return b"12345" if self.reads == 1 else b""

    monkeypatch.setattr(speech.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        speech.tempfile,
        "NamedTemporaryFile",
        lambda **_kwargs: output_path.open("w+b"),
    )
    try:
        asyncio.run(
            speech._download_voice_url(
                "https://example.com/ref.wav",
                4,
                allow_private=True,
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("oversized voice URL unexpectedly succeeded")
    assert not output_path.exists()


def test_private_voice_url_is_rejected_before_request(monkeypatch):
    from omnivoice_server.routers import speech

    opened = False

    def unexpected_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("private URL should not be opened")

    monkeypatch.setattr(speech.urllib.request, "build_opener", unexpected_open)
    try:
        asyncio.run(speech._download_voice_url("http://127.0.0.1/ref.wav", 1024))
    except ValueError as exc:
        assert "private or non-public" in str(exc)
    else:
        raise AssertionError("private voice URL unexpectedly succeeded")
    assert opened is False


def test_cancelled_voice_url_download_cleans_late_result(tmp_path, monkeypatch):
    from omnivoice_server.routers import speech

    async def exercise():
        output_path = tmp_path / "late.wav"
        release = asyncio.Event()

        async def delayed_to_thread(_function):
            await release.wait()
            output_path.write_bytes(b"late download")
            return str(output_path)

        monkeypatch.setattr(speech.asyncio, "to_thread", delayed_to_thread)
        task = asyncio.create_task(
            speech._download_voice_url(
                "https://example.com/ref.wav",
                1024,
                allow_private=True,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for _ in range(3):
            await asyncio.sleep(0)
        assert not output_path.exists()

    asyncio.run(exercise())


def test_audio_models_alias_matches_auth_exemption(settings):
    from fastapi.testclient import TestClient

    from omnivoice_server.app import create_app

    settings.api_key = "secret"
    app = create_app(settings)
    with patch("omnivoice_server.services.model.ModelService.load", new_callable=AsyncMock):
        with TestClient(app) as protected_client:
            response = protected_client.get("/v1/audio/models")
    assert response.status_code == 200


def test_explicit_sse_wav_overrides_force_stream_pcm_default(client, monkeypatch):
    monkeypatch.setattr(client.app.state.cfg, "stream", True)
    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "Explicit SSE WAV.",
            "stream_format": "sse",
            "response_format": "wav",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_private_voice_urls_default_to_disabled():
    from omnivoice_server.config import Settings

    assert Settings().allow_private_voice_urls is False
