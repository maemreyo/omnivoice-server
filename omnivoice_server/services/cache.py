"""
In-memory LRU cache for synthesis results.

Caches the encoded audio bytes (WAV) keyed on the full set of parameters
that affect model output. Designed for the common pattern where clients
repeatedly request the same (voice profile + text) combination.

Memory safety:
  - Configurable max memory cap (cache_max_mb).
  - LRU eviction: oldest-accessed entries are dropped first when the cap
    is exceeded.
  - Entries track their byte size so the budget is accurate.
  - Thread-safe via threading.Lock (cache is accessed from thread pool).

TTL enforcement:
  - Lazy: expired entries are removed on access (get returns None).
  - Active: a background asyncio task sweeps expired entries periodically
    so stale data doesn't sit in memory indefinitely.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from ..config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    audio_bytes: bytes
    media_type: str  # "audio/wav" or "audio/pcm"
    duration_s: float
    created_at: float

    @property
    def size_bytes(self) -> int:
        return len(self.audio_bytes)


def _build_cache_key(
    text: str,
    voice: str,
    speed: float,
    num_step: int,
    guidance_scale: float,
    denoise: bool,
    t_shift: float,
    position_temperature: float,
    class_temperature: float,
    duration: float | None,
    response_format: str,
) -> str:
    """
    Build a deterministic cache key from all parameters that affect output.

    Uses SHA-256 of the concatenated param string. The ``voice`` field is
    the raw client string (e.g. "clone:voice11", "design:female, british",
    "auto") — a stable semantic identifier that doesn't depend on filesystem
    paths or profile directory location.
    """
    parts = [
        text,
        voice,
        str(speed),
        str(num_step),
        str(guidance_scale),
        str(denoise),
        str(t_shift),
        str(position_temperature),
        str(class_temperature),
        str(duration) if duration is not None else "",
        response_format,
    ]
    raw = "\x00".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AudioCache:
    """
    Thread-safe LRU cache for synthesised audio bytes.

    Evicts least-recently-used entries when total memory exceeds
    cache_max_mb. All public methods are safe to call from any thread.
    """

    def __init__(self, cfg: Settings) -> None:
        self._max_bytes = cfg.cache_max_mb * 1024 * 1024
        self._ttl_s = cfg.cache_ttl_s
        self._lock = threading.Lock()
        # OrderedDict gives us O(1) move-to-end for LRU
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._current_bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._sweep_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background TTL sweep task."""
        if self._ttl_s > 0:
            self._sweep_task = asyncio.create_task(self._sweep_loop())
            logger.info(
                f"Cache TTL sweep started (interval={self._ttl_s // 2}s, ttl={self._ttl_s}s)"
            )

    async def stop(self) -> None:
        """Stop the background sweep task."""
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None

    async def _sweep_loop(self) -> None:
        """Periodically remove expired entries so stale data doesn't linger."""
        # Sweep at half the TTL interval — frequent enough to keep memory
        # honest, infrequent enough to be negligible overhead.
        interval = max(self._ttl_s // 2, 10)
        while True:
            await asyncio.sleep(interval)
            removed = self._sweep_expired()
            if removed > 0:
                logger.debug(f"TTL sweep removed {removed} expired cache entries")

    def get(self, key: str) -> _CacheEntry | None:
        """Return cached entry or None. Moves entry to MRU position."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            # Check TTL
            if self._ttl_s > 0 and (time.monotonic() - entry.created_at) > self._ttl_s:
                self._remove_locked(key)
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            self._hits += 1
            return entry

    def put(self, key: str, audio_bytes: bytes, media_type: str, duration_s: float) -> None:
        """
        Insert or replace a cache entry. Evicts LRU entries if over budget.

        Silently skips caching if a single entry exceeds the entire budget
        (avoids thrashing the whole cache for one huge response).
        """
        entry_size = len(audio_bytes)

        # Don't cache entries larger than the entire budget
        if entry_size > self._max_bytes:
            logger.debug(
                f"Skipping cache for entry of {entry_size / 1024 / 1024:.1f}MB "
                f"(exceeds {self._max_bytes / 1024 / 1024:.0f}MB budget)"
            )
            return

        entry = _CacheEntry(
            audio_bytes=audio_bytes,
            media_type=media_type,
            duration_s=duration_s,
            created_at=time.monotonic(),
        )

        with self._lock:
            # If key already exists, remove old entry's size first
            if key in self._store:
                old = self._store[key]
                self._current_bytes -= old.size_bytes
                del self._store[key]

            # Evict LRU entries until we have room
            while self._current_bytes + entry_size > self._max_bytes and self._store:
                self._evict_lru_locked()

            self._store[key] = entry
            self._current_bytes += entry_size

    def clear(self) -> None:
        """Drop all cached entries."""
        with self._lock:
            self._store.clear()
            self._current_bytes = 0

    def snapshot(self) -> dict:
        """Return cache stats for the /metrics endpoint."""
        with self._lock:
            return {
                "cache_entries": len(self._store),
                "cache_bytes": self._current_bytes,
                "cache_mb": round(self._current_bytes / 1024 / 1024, 2),
                "cache_max_mb": round(self._max_bytes / 1024 / 1024, 0),
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "cache_evictions": self._evictions,
                "cache_hit_rate": (
                    round(self._hits / (self._hits + self._misses), 3)
                    if (self._hits + self._misses) > 0
                    else 0.0
                ),
            }

    def _evict_lru_locked(self) -> None:
        """Remove the least-recently-used entry. Caller must hold _lock."""
        if not self._store:
            return
        key, entry = self._store.popitem(last=False)  # FIFO = LRU end
        self._current_bytes -= entry.size_bytes
        self._evictions += 1
        logger.debug(
            f"Evicted cache entry {key[:12]}… "
            f"({entry.size_bytes / 1024:.1f}KB, "
            f"age={time.monotonic() - entry.created_at:.0f}s)"
        )

    def _remove_locked(self, key: str) -> None:
        """Remove a specific entry. Caller must hold _lock."""
        entry = self._store.pop(key, None)
        if entry:
            self._current_bytes -= entry.size_bytes

    def _sweep_expired(self) -> int:
        """Remove all entries past TTL. Returns count of removed entries."""
        if self._ttl_s <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            expired_keys = [
                k for k, e in self._store.items()
                if (now - e.created_at) > self._ttl_s
            ]
            for key in expired_keys:
                self._remove_locked(key)
                self._evictions += 1
        return len(expired_keys)
