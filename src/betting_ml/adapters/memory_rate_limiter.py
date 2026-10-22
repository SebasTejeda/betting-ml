"""In-process RateLimiter (spec 003, US2): enough for the single API process of personal use.

With several processes or replicas each one would count on its own; swap this adapter for a
shared store (Redis) then (decisions.md).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import timedelta

MAX_KEYS = 10_000  # bounded memory: spraying keys (IPs) cannot grow it without limit


class MemoryRateLimiter:
    def __init__(
        self, clock: Callable[[], float] = time.monotonic, max_keys: int = MAX_KEYS
    ) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._locks: dict[str, float] = {}
        self._mutex = threading.Lock()

    def hit(self, key: str, limit: int, window: timedelta) -> float | None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._mutex:
            now = self._clock()
            events = self._recent(key, now, window)
            if len(events) >= limit:
                return max(events[0] + window.total_seconds() - now, 0.001)
            if key not in self._events:
                self._make_room(now)
                self._events[key] = events
            events.append(now)
            return None

    def count(self, key: str, window: timedelta) -> int:
        with self._mutex:
            return len(self._recent(key, self._clock(), window))

    def lock(self, key: str, duration: timedelta) -> None:
        with self._mutex:
            now = self._clock()
            if key not in self._locks:
                self._make_room(now)
            self._locks[key] = now + duration.total_seconds()

    def locked_for(self, key: str) -> float | None:
        with self._mutex:
            until = self._locks.get(key)
            if until is None:
                return None
            left = until - self._clock()
            if left <= 0:
                del self._locks[key]
                return None
            return left

    def reset(self, key: str) -> None:
        with self._mutex:
            self._events.pop(key, None)
            self._locks.pop(key, None)

    def _recent(self, key: str, now: float, window: timedelta) -> deque[float]:
        events = self._events.get(key, deque())
        while events and events[0] <= now - window.total_seconds():
            events.popleft()
        return events

    def _make_room(self, now: float) -> None:
        """Before adding a key: drop expired locks and empty counters, then the oldest keys."""
        if len(self._events) + len(self._locks) < self._max_keys:
            return
        for key in [k for k, until in self._locks.items() if until <= now]:
            del self._locks[key]
        for key in [k for k, events in self._events.items() if not events]:
            del self._events[key]
        while self._events and len(self._events) + len(self._locks) >= self._max_keys:
            del self._events[next(iter(self._events))]
