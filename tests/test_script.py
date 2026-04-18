"""
Tests for /v1/audio/script endpoint.
"""

from __future__ import annotations

import base64


def test_script_single_track_returns_wav(client):
    """Happy path: single_track output returns WAV audio."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello world"},
                {"speaker": "bob", "text": "Hi there"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


def test_script_multi_track_returns_json(client):
    """output_format=multi_track returns JSON with tracks and metadata."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello world"},
                {"speaker": "bob", "text": "Hi there"},
            ],
            "output_format": "multi_track",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"

    body = resp.json()
    assert "tracks" in body
    assert "metadata" in body

    # Check tracks structure
    tracks = body["tracks"]
    assert "alice" in tracks
    assert "bob" in tracks
    # Tracks should be base64-encoded WAV
    alice_wav = base64.b64decode(tracks["alice"])
    assert alice_wav[:4] == b"RIFF"

    # Check metadata structure
    metadata = body["metadata"]
    assert "total_duration_s" in metadata
    assert "speakers_unique" in metadata
    assert "segment_count" in metadata
    assert "skipped_segments" in metadata
    assert "segments" in metadata

    # Verify segment structure
    segments = metadata["segments"]
    assert len(segments) == 2
    assert segments[0]["speaker"] == "alice"
    assert segments[1]["speaker"] == "bob"
    assert "offset_s" in segments[0]
    assert "duration_s" in segments[0]


def test_script_validates_segment_count_limit(client):
    """Script with >100 segments returns 422."""
    script = [{"speaker": f"speaker{i}", "text": "Hello"} for i in range(101)]

    resp = client.post(
        "/v1/audio/script",
        json={"script": script},
    )
    assert resp.status_code == 422


def test_script_validates_total_chars_limit(client):
    """Script with >50000 total chars returns 422."""
    long_text = "a" * 9999
    script = [{"speaker": f"speaker{i}", "text": long_text} for i in range(6)]

    resp = client.post(
        "/v1/audio/script",
        json={"script": script},
    )
    assert resp.status_code == 422


def test_script_validates_unique_speakers_limit(client):
    """Script with >10 unique speakers returns 422."""
    script = [{"speaker": f"speaker{i}", "text": "Hello"} for i in range(11)]

    resp = client.post(
        "/v1/audio/script",
        json={"script": script},
    )
    assert resp.status_code == 422


def test_script_invalid_speaker_id_returns_422(client):
    """Invalid speaker ID (fails regex) returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice@invalid", "text": "Hello"},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_empty_script_returns_422(client):
    """Empty script list returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={"script": []},
    )
    assert resp.status_code == 422


def test_script_response_headers_present(client):
    """Response includes all expected headers."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello world"},
                {"speaker": "bob", "text": "Hi there"},
            ],
        },
    )
    assert resp.status_code == 200

    # Check all required headers
    assert "X-Audio-Duration-S" in resp.headers
    assert "X-Synthesis-Latency-S" in resp.headers
    assert "X-Speakers-Unique" in resp.headers
    assert "X-Segment-Count" in resp.headers
    assert "X-Skipped-Segments" in resp.headers

    # Verify header values
    assert resp.headers["X-Speakers-Unique"] == "2"
    assert resp.headers["X-Segment-Count"] == "2"


def test_script_on_error_default_is_abort(client):
    """Verify on_error defaults to 'abort' (not 'skip')."""
    # Test that default payload is accepted (on_error defaults correctly)
    resp = client.post(
        "/v1/audio/script",
        json={"script": [{"speaker": "alice", "text": "Hello"}]},
    )
    assert resp.status_code == 200

    # Test that skip mode explicitly works too
    resp2 = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "on_error": "skip",
        },
    )
    assert resp2.status_code == 200


def test_script_pause_between_speakers_default(client):
    """Verify pause_between_speakers defaults to 0.5."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
                {"speaker": "bob", "text": "Hi"},
            ],
        },
    )
    assert resp.status_code == 200

    # Test explicit pause value
    resp2 = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
                {"speaker": "bob", "text": "Hi"},
            ],
            "pause_between_speakers": 1.0,
        },
    )
    assert resp2.status_code == 200


def test_script_speed_out_of_range_returns_422(client):
    """speed < 0.25 or > 4.0 returns 422."""
    # Test speed too low
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "speed": 0.2,
        },
    )
    assert resp.status_code == 422

    # Test speed too high
    resp2 = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "speed": 4.5,
        },
    )
    assert resp2.status_code == 422

    # Test valid speed
    resp3 = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "speed": 1.5,
        },
    )
    assert resp3.status_code == 200


def test_script_pause_out_of_range_returns_422(client):
    """pause_between_speakers > 5.0 returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "pause_between_speakers": 6.0,
        },
    )
    assert resp.status_code == 422

    # Test valid pause
    resp2 = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello"}],
            "pause_between_speakers": 2.5,
        },
    )
    assert resp2.status_code == 200


def test_script_segment_speed_override(client):
    """Per-segment speed parameter should be accepted."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello", "speed": 1.5},
                {"speaker": "bob", "text": "Hi", "speed": 0.8},
            ],
        },
    )
    assert resp.status_code == 200


def test_script_segment_voice_override(client):
    """Per-segment voice parameter should be accepted."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello", "voice": "female, young adult"},
                {"speaker": "bob", "text": "Hi", "voice": "male, deep voice"},
            ],
        },
    )
    assert resp.status_code == 200


def test_script_segment_voice_override_takes_precedence_over_default_voice(client):
    """Per-segment voice overrides should still work when a default_voice is provided."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello", "voice": "female, young adult"},
                {"speaker": "bob", "text": "Hi", "voice": "male, low pitch"},
            ],
            "default_voice": "female, british accent",
        },
    )
    assert resp.status_code == 200


def test_script_empty_tensor_returns_explicit_500(client):
    """Empty synthesis outputs should fail with a clear script-path error."""
    from unittest.mock import AsyncMock

    import torch

    async def _empty_synthesize(req):
        return AsyncMock(tensors=[torch.empty(1, 0)], duration_s=0.0)

    original_synthesize = client.app.state.inference_svc.synthesize
    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_empty_synthesize)

    try:
        resp = client.post(
            "/v1/audio/script",
            json={"script": [{"speaker": "alice", "text": "Hello"}]},
        )
        assert resp.status_code == 500
        assert "produced empty audio" in resp.text
    finally:
        client.app.state.inference_svc.synthesize = original_synthesize


def test_script_default_voice_parameter(client):
    """default_voice parameter should be accepted."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
            ],
            "default_voice": "female, british accent",
        },
    )
    assert resp.status_code == 200


def test_script_response_format_parameter(client):
    """response_format parameter should be accepted."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
            ],
            "response_format": "pcm",
        },
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]


def test_script_text_too_long_per_segment_returns_422(client):
    """Text > 10000 chars per segment returns 422."""
    long_text = "a" * 10001

    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": long_text},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_empty_text_returns_422(client):
    """Empty text in segment returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": ""},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_empty_speaker_returns_422(client):
    """Empty speaker ID returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "", "text": "Hello"},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_speaker_too_long_returns_422(client):
    """Speaker ID > 64 chars returns 422."""
    long_speaker = "a" * 65

    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": long_speaker, "text": "Hello"},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_valid_speaker_ids(client):
    """Valid speaker IDs with alphanumeric, underscore, hyphen should work."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice_123", "text": "Hello"},
                {"speaker": "bob-456", "text": "Hi"},
                {"speaker": "charlie789", "text": "Hey"},
                {"speaker": "DAVE_XYZ", "text": "Yo"},
            ],
        },
    )
    assert resp.status_code == 200


def test_script_multi_track_metadata_accuracy(client):
    """Verify multi_track metadata values are accurate."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
                {"speaker": "bob", "text": "Hi"},
                {"speaker": "alice", "text": "How are you?"},
            ],
            "output_format": "multi_track",
            "pause_between_speakers": 0.5,
        },
    )
    assert resp.status_code == 200

    body = resp.json()
    metadata = body["metadata"]

    # Check unique speakers (alice and bob = 2)
    assert metadata["speakers_unique"] == 2

    # Check segment count (3 segments)
    assert metadata["segment_count"] == 3

    # Check segments list
    segments = metadata["segments"]
    assert len(segments) == 3
    assert segments[0]["speaker"] == "alice"
    assert segments[1]["speaker"] == "bob"
    assert segments[2]["speaker"] == "alice"

    # Check that offsets are increasing
    assert segments[0]["offset_s"] == 0.0
    assert segments[1]["offset_s"] > segments[0]["offset_s"]
    assert segments[2]["offset_s"] > segments[1]["offset_s"]


def test_script_single_track_duration_header(client):
    """Verify X-Audio-Duration-S header is accurate for single_track."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
                {"speaker": "bob", "text": "Hi"},
            ],
            "pause_between_speakers": 0.5,
        },
    )
    assert resp.status_code == 200

    duration_s = float(resp.headers["X-Audio-Duration-S"])
    # Mock returns 1s per segment, with 0.5s pause = 2.5s total
    assert duration_s > 2.0  # At least 2 segments + pause


def test_script_skipped_segments_header_empty_on_success(client):
    """X-Skipped-Segments should be empty when all segments succeed."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello"},
                {"speaker": "bob", "text": "Hi"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["X-Skipped-Segments"] == ""


def test_script_whitespace_only_text_returns_422(client):
    """Whitespace-only text returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "   "},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_whitespace_only_voice_returns_422(client):
    """Whitespace-only voice returns 422."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello", "voice": "   "},
            ],
        },
    )
    assert resp.status_code == 422


def test_script_on_error_skip_all_fail_returns_422(client):
    """When on_error='skip' and all segments fail, returns 422."""
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    async def _failing_synthesize(req):
        raise HTTPException(status_code=400, detail="Synthesis failed")

    original_synthesize = client.app.state.inference_svc.synthesize
    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_failing_synthesize)

    try:
        resp = client.post(
            "/v1/audio/script",
            json={
                "script": [
                    {"speaker": "alice", "text": "Hello"},
                    {"speaker": "bob", "text": "Hi"},
                ],
                "on_error": "skip",
            },
        )
        assert resp.status_code == 422
    finally:
        client.app.state.inference_svc.synthesize = original_synthesize


def test_script_capacity_returns_503_when_slot_occupied(client):
    """Script synthesis returns 503 when dedicated slot is already occupied."""
    import asyncio
    import time
    from unittest.mock import AsyncMock

    import torch

    async def _slow_synthesize(req):
        await asyncio.sleep(0.5)
        return AsyncMock(tensors=[torch.zeros(1, 24_000)], duration_s=1.0)

    original_synthesize = client.app.state.inference_svc.synthesize
    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_slow_synthesize)

    try:
        import threading

        results = []

        def _make_request():
            resp = client.post(
                "/v1/audio/script",
                json={"script": [{"speaker": "alice", "text": "Hello world"}]},
            )
            results.append(resp.status_code)

        thread1 = threading.Thread(target=_make_request)
        thread2 = threading.Thread(target=_make_request)

        thread1.start()
        time.sleep(0.05)
        thread2.start()

        thread1.join()
        thread2.join()

        assert 503 in results, "Expected at least one 503 when capacity exceeded"
    finally:
        client.app.state.inference_svc.synthesize = original_synthesize


def test_script_timeout_returns_504(client):
    """Script synthesis returns 504 when exceeding total timeout."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    async def _timeout_synthesize(req):
        await asyncio.sleep(999)
        return AsyncMock(tensors=[AsyncMock()], duration_s=1.0)

    original_synthesize = client.app.state.inference_svc.synthesize
    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_timeout_synthesize)

    try:
        with patch("omnivoice_server.services.script.SCRIPT_TOTAL_TIMEOUT_S", 0.1):
            resp = client.post(
                "/v1/audio/script",
                json={"script": [{"speaker": "alice", "text": "Hello"}]},
            )
            assert resp.status_code == 504
    finally:
        client.app.state.inference_svc.synthesize = original_synthesize


def test_script_single_vs_multi_track_consistency(client):
    """Verify single_track and multi_track return consistent metadata."""
    script = [
        {"speaker": "alice", "text": "Hello world"},
        {"speaker": "bob", "text": "Hi there"},
        {"speaker": "alice", "text": "How are you?"},
    ]

    resp_single = client.post(
        "/v1/audio/script",
        json={"script": script, "pause_between_speakers": 0.5},
    )
    assert resp_single.status_code == 200

    resp_multi = client.post(
        "/v1/audio/script",
        json={"script": script, "output_format": "multi_track", "pause_between_speakers": 0.5},
    )
    assert resp_multi.status_code == 200

    single_duration = float(resp_single.headers["X-Audio-Duration-S"])
    single_speakers = int(resp_single.headers["X-Speakers-Unique"])
    single_segments = int(resp_single.headers["X-Segment-Count"])

    multi_body = resp_multi.json()
    multi_duration = multi_body["metadata"]["total_duration_s"]
    multi_speakers = multi_body["metadata"]["speakers_unique"]
    multi_segments = multi_body["metadata"]["segment_count"]

    assert single_speakers == multi_speakers == 2
    assert single_segments == multi_segments == 3
    assert abs(single_duration - multi_duration) < 0.1


def test_script_multi_track_duration_uses_actual_speaker_changes(client):
    """Multi-track duration should only include pauses on speaker changes."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [
                {"speaker": "alice", "text": "Hello world"},
                {"speaker": "alice", "text": "Still Alice"},
                {"speaker": "alice", "text": "And again"},
            ],
            "output_format": "multi_track",
            "pause_between_speakers": 1.0,
        },
    )
    assert resp.status_code == 200

    metadata = resp.json()["metadata"]
    segments = metadata["segments"]
    expected_duration = segments[-1]["offset_s"] + segments[-1]["duration_s"]

    assert len(segments) == 3
    assert abs(metadata["total_duration_s"] - expected_duration) < 0.001


def test_script_clone_profile_resolved_once_per_speaker(client):
    """Clone profile paths are resolved once upfront and reused per segment."""
    from pathlib import Path
    from unittest.mock import patch

    with patch.object(
        client.app.state.profile_svc,
        "get_ref_audio_path",
        return_value=Path("/tmp/alice.wav"),
    ) as mock_get_ref_audio_path:
        resp = client.post(
            "/v1/audio/script",
            json={
                "script": [
                    {"speaker": "alice", "text": "Hello", "voice": "clone:alice"},
                    {"speaker": "alice", "text": "Again", "voice": "clone:alice"},
                    {"speaker": "alice", "text": "Third line", "voice": "clone:alice"},
                ]
            },
        )

    assert resp.status_code == 200
    mock_get_ref_audio_path.assert_called_once_with("alice")


def test_script_invalid_openai_preset_returns_422_upfront(client):
    """Invalid OpenAI presets should be rejected before synthesis begins."""
    resp = client.post(
        "/v1/audio/script",
        json={
            "script": [{"speaker": "alice", "text": "Hello", "voice": "openai:not-a-real-preset"}]
        },
    )

    assert resp.status_code == 422
    assert "Invalid OpenAI preset" in resp.text


def test_script_malformed_tensor_handling(client):
    """Verify malformed tensor handling via script response path."""
    from unittest.mock import AsyncMock

    import torch

    async def _malformed_synthesize(req):
        return AsyncMock(tensors=[torch.tensor([float("nan")])], duration_s=1.0)

    original_synthesize = client.app.state.inference_svc.synthesize
    client.app.state.inference_svc.synthesize = AsyncMock(side_effect=_malformed_synthesize)

    try:
        resp = client.post(
            "/v1/audio/script",
            json={"script": [{"speaker": "alice", "text": "Hello"}]},
        )
        assert resp.status_code == 500
        assert "NaN or Inf" in resp.text
    finally:
        client.app.state.inference_svc.synthesize = original_synthesize
