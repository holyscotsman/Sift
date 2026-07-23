"""Sliding-window failed-login limiter.

Keyed by username, not client address — the server commonly sits behind a proxy
where every request shares one IP, and it's the *account* that needs protecting
from brute force. In-memory only (single-process server); a success clears the
window so a legitimate owner is never locked out after logging in.
"""

from __future__ import annotations

import time
from collections import deque


class LoginRateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: float = 60.0) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._fails: dict[str, deque[float]] = {}

    def retry_after(self, username: str) -> int | None:
        """Seconds until another attempt is allowed, or None if not limited."""
        q = self._fails.get(username)
        if not q:
            return None
        now = time.monotonic()
        while q and now - q[0] > self._window:
            q.popleft()
        if not q:
            del self._fails[username]
            return None
        if len(q) >= self._max:
            return max(1, int(self._window - (now - q[0])) + 1)
        return None

    def record_failure(self, username: str) -> None:
        self._fails.setdefault(username, deque()).append(time.monotonic())

    def record_success(self, username: str) -> None:
        self._fails.pop(username, None)
