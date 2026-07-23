"""Process-local cache for the expensive /api/status queue counts.

``junk_flagged`` re-scores the whole library through ``junk.candidates`` and the
dashboard polls /api/status every few seconds — without a cache the same number is
recomputed dozens of times a minute. The TTL is only a backstop: every write path
that can change the numbers (keep-overrides, threshold saves, scan completion,
must-have runs/dismissals) calls :meth:`invalidate` so the next poll is exact.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class CountsCache:
    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._value: tuple[int, int] | None = None
        self._at = 0.0

    def get(self, compute: Callable[[], tuple[int, int]]) -> tuple[int, int]:
        """Return (junk_flagged, musthave_pending), computing at most once per TTL."""
        now = time.monotonic()
        if self._value is not None and now - self._at < self._ttl:
            return self._value
        self._value = compute()
        self._at = now
        return self._value

    def invalidate(self) -> None:
        self._value = None
