"""
In-memory request metrics. Thread-safe with a lock.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class StreamObservation:
    request_id: str
    mode: str
    profile_id: str | None
    input_chars: int
    planned_synthesis_calls: int
    first_chunk_chars: int
    completed_synthesis_calls: int
    emitted_audio_chunks: int
    emitted_bytes: int
    status: str
    sentence_split_ms: float
    ttfa_ms: float | None
    first_synthesis_ms: float | None
    first_clone_prompt_ms: float | None
    first_decode_postprocess_ms: float | None
    first_postprocess_ms: float | None
    first_decode_only_ms: float | None
    first_cleanup_ms: float | None
    first_pcm_encode_ms: float | None
    first_prepare_inference_calls: int | None = None
    first_batch_size: int | None = None
    first_max_condition_len: int | None = None
    first_max_target_tokens: int | None = None
    first_max_ref_audio_tokens: int | None = None
    first_attention_mask_mb_estimate: float | None = None
    first_batch_logits_mb_estimate: float | None = None
    first_tokens_mb_estimate: float | None = None
    first_cuda_allocated_before_mb: float | None = None
    first_cuda_allocated_after_mb: float | None = None
    first_cuda_reserved_before_mb: float | None = None
    first_cuda_reserved_after_mb: float | None = None
    first_cuda_free_before_mb: float | None = None
    first_cuda_free_after_mb: float | None = None
    first_cuda_total_mb: float | None = None
    total_ms: float | None = None


class MetricsService:
    def __init__(self, latency_window: int = 200) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.success = 0
        self.error = 0
        self.timeout = 0
        self._latencies: deque[float] = deque(maxlen=latency_window)
        self.streaming_total = 0
        self.streaming_success = 0
        self.streaming_error = 0
        self.streaming_timeout = 0
        self.streaming_auto = 0
        self.streaming_design = 0
        self.streaming_clone = 0
        self._stream_ttfa_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_synthesis_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_clone_prompt_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_decode_postprocess_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_postprocess_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_decode_only_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_cleanup_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_first_pcm_encode_ms: deque[float] = deque(maxlen=latency_window)
        self._stream_total_ms: deque[float] = deque(maxlen=latency_window)
        self._latest_stream: dict[str, Any] | None = None

    def record_success(self, latency_s: float) -> None:
        with self._lock:
            self.total += 1
            self.success += 1
            self._latencies.append(latency_s * 1000)  # store as ms

    def record_error(self) -> None:
        with self._lock:
            self.total += 1
            self.error += 1

    def record_timeout(self) -> None:
        with self._lock:
            self.total += 1
            self.timeout += 1

    def record_stream_observation(self, observation: StreamObservation) -> None:
        with self._lock:
            self.streaming_total += 1

            if observation.mode == "clone":
                self.streaming_clone += 1
            elif observation.mode == "design":
                self.streaming_design += 1
            else:
                self.streaming_auto += 1

            if observation.status == "success":
                self.streaming_success += 1
            elif observation.status == "timeout":
                self.streaming_timeout += 1
            else:
                self.streaming_error += 1

            if observation.ttfa_ms is not None:
                self._stream_ttfa_ms.append(observation.ttfa_ms)
            if observation.first_synthesis_ms is not None:
                self._stream_first_synthesis_ms.append(observation.first_synthesis_ms)
            if observation.first_clone_prompt_ms is not None:
                self._stream_first_clone_prompt_ms.append(observation.first_clone_prompt_ms)
            if observation.first_decode_postprocess_ms is not None:
                self._stream_first_decode_postprocess_ms.append(
                    observation.first_decode_postprocess_ms
                )
            if observation.first_postprocess_ms is not None:
                self._stream_first_postprocess_ms.append(observation.first_postprocess_ms)
            if observation.first_decode_only_ms is not None:
                self._stream_first_decode_only_ms.append(observation.first_decode_only_ms)
            if observation.first_cleanup_ms is not None:
                self._stream_first_cleanup_ms.append(observation.first_cleanup_ms)
            if observation.first_pcm_encode_ms is not None:
                self._stream_first_pcm_encode_ms.append(observation.first_pcm_encode_ms)
            if observation.total_ms is not None:
                self._stream_total_ms.append(observation.total_ms)

            self._latest_stream = {
                "request_id": observation.request_id,
                "status": observation.status,
                "mode": observation.mode,
                "profile_id": observation.profile_id,
                "input_chars": observation.input_chars,
                "planned_synthesis_calls": observation.planned_synthesis_calls,
                "first_chunk_chars": observation.first_chunk_chars,
                "completed_synthesis_calls": observation.completed_synthesis_calls,
                "emitted_audio_chunks": observation.emitted_audio_chunks,
                "emitted_bytes": observation.emitted_bytes,
                "sentence_split_ms": round(observation.sentence_split_ms, 1),
                "ttfa_ms": _round_ms(observation.ttfa_ms),
                "first_synthesis_ms": _round_ms(observation.first_synthesis_ms),
                "first_clone_prompt_ms": _round_ms(observation.first_clone_prompt_ms),
                "first_decode_postprocess_ms": _round_ms(
                    observation.first_decode_postprocess_ms
                ),
                "first_postprocess_ms": _round_ms(observation.first_postprocess_ms),
                "first_decode_only_ms": _round_ms(observation.first_decode_only_ms),
                "first_cleanup_ms": _round_ms(observation.first_cleanup_ms),
                "first_pcm_encode_ms": _round_ms(observation.first_pcm_encode_ms),
                "first_prepare_inference_calls": observation.first_prepare_inference_calls,
                "first_batch_size": observation.first_batch_size,
                "first_max_condition_len": observation.first_max_condition_len,
                "first_max_target_tokens": observation.first_max_target_tokens,
                "first_max_ref_audio_tokens": observation.first_max_ref_audio_tokens,
                "first_attention_mask_mb_estimate": _round_ms(
                    observation.first_attention_mask_mb_estimate
                ),
                "first_batch_logits_mb_estimate": _round_ms(
                    observation.first_batch_logits_mb_estimate
                ),
                "first_tokens_mb_estimate": _round_ms(observation.first_tokens_mb_estimate),
                "first_cuda_allocated_before_mb": _round_ms(
                    observation.first_cuda_allocated_before_mb
                ),
                "first_cuda_allocated_after_mb": _round_ms(
                    observation.first_cuda_allocated_after_mb
                ),
                "first_cuda_reserved_before_mb": _round_ms(
                    observation.first_cuda_reserved_before_mb
                ),
                "first_cuda_reserved_after_mb": _round_ms(
                    observation.first_cuda_reserved_after_mb
                ),
                "first_cuda_free_before_mb": _round_ms(observation.first_cuda_free_before_mb),
                "first_cuda_free_after_mb": _round_ms(observation.first_cuda_free_after_mb),
                "first_cuda_total_mb": _round_ms(observation.first_cuda_total_mb),
                "total_ms": _round_ms(observation.total_ms),
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lats = list(self._latencies)
            stream_ttfa = list(self._stream_ttfa_ms)
            stream_first_synthesis = list(self._stream_first_synthesis_ms)
            stream_first_clone_prompt = list(self._stream_first_clone_prompt_ms)
            stream_first_decode_postprocess = list(self._stream_first_decode_postprocess_ms)
            stream_first_postprocess = list(self._stream_first_postprocess_ms)
            stream_first_decode_only = list(self._stream_first_decode_only_ms)
            stream_first_cleanup = list(self._stream_first_cleanup_ms)
            stream_first_pcm_encode = list(self._stream_first_pcm_encode_ms)
            stream_total = list(self._stream_total_ms)
            latest_stream = self._latest_stream

        mean_ms = sum(lats) / len(lats) if lats else 0.0
        sorted_lats = sorted(lats)
        p95_ms = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0
        snapshot: dict[str, Any] = {
            "requests_total": self.total,
            "requests_success": self.success,
            "requests_error": self.error,
            "requests_timeout": self.timeout,
            "mean_latency_ms": round(mean_ms, 1),
            "p95_latency_ms": round(p95_ms, 1),
        }
        snapshot.update(
            {
                "streaming_requests_total": self.streaming_total,
                "streaming_requests_success": self.streaming_success,
                "streaming_requests_error": self.streaming_error,
                "streaming_requests_timeout": self.streaming_timeout,
                "streaming_auto_requests": self.streaming_auto,
                "streaming_design_requests": self.streaming_design,
                "streaming_clone_requests": self.streaming_clone,
                "streaming_ttfa_ms_mean": _mean_ms(stream_ttfa),
                "streaming_ttfa_ms_p95": _p95_ms(stream_ttfa),
                "streaming_first_synthesis_ms_mean": _mean_ms(stream_first_synthesis),
                "streaming_first_synthesis_ms_p95": _p95_ms(stream_first_synthesis),
                "streaming_first_clone_prompt_ms_mean": _mean_ms(stream_first_clone_prompt),
                "streaming_first_clone_prompt_ms_p95": _p95_ms(stream_first_clone_prompt),
                "streaming_first_decode_postprocess_ms_mean": _mean_ms(
                    stream_first_decode_postprocess
                ),
                "streaming_first_decode_postprocess_ms_p95": _p95_ms(
                    stream_first_decode_postprocess
                ),
                "streaming_first_postprocess_ms_mean": _mean_ms(stream_first_postprocess),
                "streaming_first_postprocess_ms_p95": _p95_ms(stream_first_postprocess),
                "streaming_first_decode_only_ms_mean": _mean_ms(stream_first_decode_only),
                "streaming_first_decode_only_ms_p95": _p95_ms(stream_first_decode_only),
                "streaming_first_cleanup_ms_mean": _mean_ms(stream_first_cleanup),
                "streaming_first_cleanup_ms_p95": _p95_ms(stream_first_cleanup),
                "streaming_first_pcm_encode_ms_mean": _mean_ms(stream_first_pcm_encode),
                "streaming_first_pcm_encode_ms_p95": _p95_ms(stream_first_pcm_encode),
                "streaming_total_ms_mean": _mean_ms(stream_total),
                "streaming_total_ms_p95": _p95_ms(stream_total),
                "streaming_latest": latest_stream,
            }
        )
        return snapshot


def _mean_ms(values: list[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _p95_ms(values: list[float]) -> float:
    return round(sorted(values)[int(len(values) * 0.95)], 1) if values else 0.0


def _round_ms(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 1)
