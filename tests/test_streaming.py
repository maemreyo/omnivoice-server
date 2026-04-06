"""
Tests for streaming synthesis endpoint.

The streaming test was previously buried in test_voices.py — moved here where
it belongs, with additional edge-case coverage.
"""

from __future__ import annotations


def test_streaming_returns_pcm_headers(client):
    """Streaming response must set the PCM metadata headers."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello world. This is sentence two.", "stream": True},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Audio-Sample-Rate") == "24000"
    assert resp.headers.get("X-Audio-Channels") == "1"
    assert resp.headers.get("X-Audio-Bit-Depth") == "16"
    assert resp.headers.get("X-Audio-Format") == "pcm-int16-le"
    assert resp.headers.get("X-Request-Id")


def test_streaming_content_type_is_pcm(client):
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True},
    )
    assert resp.status_code == 200
    assert "audio/pcm" in resp.headers["content-type"]


def test_streaming_returns_bytes(client):
    """Should yield at least some PCM bytes for non-empty input."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello world.", "stream": True},
    )
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_streaming_multi_sentence(client):
    """Multiple sentences should all be synthesized.

    Streaming now emits the first natural sentence immediately for lower TTFA,
    then merges remaining short sentences. With the mocked inference service,
    each synthesis call returns 1s of silence, so 2 synthesis calls yield 96KB.
    """
    text = "First sentence. Second sentence. Third sentence."
    resp = client.post(
        "/v1/audio/speech",
        json={"input": text, "stream": True},
    )
    assert resp.status_code == 200
    assert len(resp.content) >= 96000


def test_streaming_with_clone_voice(client, sample_audio_bytes):
    """Streaming should work with clone: prefix too."""
    import io

    # Create profile first
    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "stream-test"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "voice": "clone:stream-test", "stream": True},
    )
    assert resp.status_code == 200


def test_streaming_clone_metrics_are_recorded(client, sample_audio_bytes):
    """Streaming clone requests should populate TTFA metrics and latest stream snapshot."""
    import io

    client.post(
        "/v1/voices/profiles",
        data={"profile_id": "sky"},
        files={"ref_audio": ("ref.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )

    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello. Streaming metrics.", "voice": "clone:sky", "stream": True},
    )
    assert resp.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    data = metrics.json()
    assert data["requests_total"] == 1
    assert data["requests_success"] == 1
    assert data["streaming_requests_total"] == 1
    assert data["streaming_requests_success"] == 1
    assert data["streaming_clone_requests"] == 1
    assert data["streaming_ttfa_ms_mean"] >= 0.0
    latest = data["streaming_latest"]
    assert latest is not None
    assert latest["mode"] == "clone"
    assert latest["profile_id"] == "sky"
    assert latest["status"] == "success"
    assert latest["ttfa_ms"] is not None
    assert latest["planned_synthesis_calls"] == 2
    assert latest["first_chunk_chars"] == len("Hello.")
    assert latest["first_clone_prompt_ms"] == 12.0
    assert latest["first_decode_postprocess_ms"] == 8.0
    assert latest["first_postprocess_ms"] == 3.0
    assert latest["first_decode_only_ms"] == 5.0
    assert latest["first_cleanup_ms"] == 0.0
    assert latest["first_prepare_inference_calls"] == 1
    assert latest["first_batch_size"] == 1
    assert latest["first_max_condition_len"] == 64
    assert latest["first_max_target_tokens"] == 25
    assert latest["first_max_ref_audio_tokens"] == 12
    assert latest["first_attention_mask_mb_estimate"] == 0.0
    assert latest["first_batch_logits_mb_estimate"] == 1.5
    assert latest["first_tokens_mb_estimate"] == 0.0
    assert latest["first_cuda_allocated_before_mb"] == 100.0
    assert latest["first_cuda_allocated_after_mb"] == 120.0
    assert latest["first_cuda_reserved_before_mb"] == 128.0
    assert latest["first_cuda_reserved_after_mb"] == 256.0
    assert latest["first_cuda_free_before_mb"] == 8000.0
    assert latest["first_cuda_free_after_mb"] == 7900.0
    assert latest["first_cuda_total_mb"] == 16384.0


def test_streaming_empty_text_rejected(client):
    """Empty text should be rejected by Pydantic validation, not silently pass."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "", "stream": True},
    )
    assert resp.status_code == 422


def test_streaming_nonexistent_profile_rejected(client):
    """clone: prefix with unknown profile should return 404 even in streaming mode."""
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "voice": "clone:does-not-exist", "stream": True},
    )
    assert resp.status_code == 404


def test_streaming_does_not_return_wav_header(client):
    """
    PCM stream must NOT start with RIFF — that would be a WAV header embedded
    in a raw PCM stream, which would corrupt the audio.
    """
    resp = client.post(
        "/v1/audio/speech",
        json={"input": "Hello.", "stream": True},
    )
    assert resp.status_code == 200
    if len(resp.content) >= 4:
        assert resp.content[:4] != b"RIFF", (
            "Streaming returned WAV header in PCM stream — "
            "check that streaming uses tensor_to_pcm16_bytes, not tensors_to_wav_bytes"
        )
