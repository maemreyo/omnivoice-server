"""
In-memory request metrics. Thread-safe with a lock.
"""

from __future__ import annotations

import threading
from collections import deque


class MetricsService:
    def __init__(self, latency_window: int = 200) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.success = 0
        self.error = 0
        self.timeout = 0
        self.batches_dispatched = 0
        self.total_batch_size = 0
        self._latencies: deque[float] = deque(maxlen=latency_window)

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

    def record_batch(self, batch_size: int) -> None:
        """Record a batch dispatch event."""
        with self._lock:
            self.batches_dispatched += 1
            self.total_batch_size += batch_size

    def snapshot(self) -> dict:
        with self._lock:
            lats = list(self._latencies)
            avg_batch = (
                self.total_batch_size / self.batches_dispatched
                if self.batches_dispatched > 0
                else 0.0
            )
        mean_ms = sum(lats) / len(lats) if lats else 0.0
        sorted_lats = sorted(lats)
        p95_ms = sorted_lats[int(len(sorted_lats) * 0.95)] if sorted_lats else 0.0
        return {
            "requests_total": self.total,
            "requests_success": self.success,
            "requests_error": self.error,
            "requests_timeout": self.timeout,
            "mean_latency_ms": round(mean_ms, 1),
            "p95_latency_ms": round(p95_ms, 1),
            "batches_dispatched": self.batches_dispatched,
            "avg_batch_size": round(avg_batch, 2),
        }
