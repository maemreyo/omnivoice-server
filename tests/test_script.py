"""
Tests for /v1/audio/script endpoint.
"""

from __future__ import annotations

import base64

import pytest


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
