"""Tiny in-memory TTL cache and per-client rate limiter (good enough for one instance)."""

from __future__ import annotations

import time
from collections import deque
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int, max_items: int = 512):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if len(self._data) >= self.max_items:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest, None)
        self._data[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._data.clear()


class RateLimiter:
    """Sliding-window limiter: at most `limit` hits per `window` seconds per key.

    Idle keys are swept out so memory stays bounded even with many different clients.
    """

    def __init__(self, limit: int, window: float = 60.0, max_keys: int = 10_000):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._hits: dict[str, deque] = {}

    def _sweep(self, now: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window]
        for k in stale:
            del self._hits[k]

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if key not in self._hits and len(self._hits) >= self.max_keys:
            self._sweep(now)
            if len(self._hits) >= self.max_keys:
                return False
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
