"""Shared async HTTP client base.

Every source client subclasses :class:`BaseClient`, which centralises:

- **retry with exponential backoff + full jitter** (idempotent methods and 429/503
  only, honouring ``Retry-After``),
- **rate limiting** (a minimum spacing between requests, TMDB the tightest),
- **secret redaction** so tokens never appear in raised errors or logs,
- a uniform :meth:`health` probe shape.

Timing dependencies (``sleep``, ``clock``, ``rng``) are injectable so tests are
fast and deterministic — no real sleeping, no wall-clock flakiness.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

# Methods safe to retry on a transport error or 5xx without risking a duplicate
# side effect. 429/503 are retried for *any* method (the server explicitly asked).
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRY_AFTER_STATUSES = frozenset({429, 503})
RETRIABLE_5XX = frozenset({500, 502, 503, 504})


class ClientError(Exception):
    """Base class for all Sift client errors (secrets already redacted)."""


class ClientAuthError(ClientError):
    """401/403 — bad or missing credentials."""


class ClientHTTPError(ClientError):
    """A non-retriable 4xx (other than auth)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class ClientUnavailableError(ClientError):
    """The service is unreachable or kept failing after all retries."""


@dataclass(frozen=True)
class HealthStatus:
    service: str
    ok: bool
    detail: str = ""
    latency_ms: float | None = None


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: bool = True

    def backoff(self, attempt: int, rng: Callable[[], float]) -> float:
        """Full-jitter backoff for a zero-based attempt index."""
        ceiling: float = min(self.max_delay, self.base_delay * (2**attempt))
        if not self.jitter:
            return ceiling
        return rng() * ceiling


class RateLimiter:
    """Enforce a minimum interval between acquisitions (per client instance)."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                await self._sleep(wait)
                now = self._clock()
            self._next_allowed = now + self.min_interval


class BaseClient:
    def __init__(
        self,
        service: str,
        base_url: str | None,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: float = 15.0,
        retry: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        secrets: Sequence[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        health_path: str = "/",
    ) -> None:
        if not base_url:
            raise ClientError(f"{service}: base_url is not configured")
        self.service = service
        self.retry = retry or RetryPolicy()
        self.rate_limiter = rate_limiter or RateLimiter(0.0)
        self._sleep = sleep
        self._rng = rng
        self._health_path = health_path
        # Redact any secret substrings (and their non-empty values) from errors.
        self._secrets = [s for s in (secrets or []) if s]
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> BaseClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _redact(self, text: str) -> str:
        out = text
        for secret in self._secrets:
            out = out.replace(secret, "***")
        return out

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None  # HTTP-date form is uncommon here; fall back to backoff.

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        method = method.upper()
        idempotent = method in IDEMPOTENT_METHODS
        last_exc: Exception | None = None

        for attempt in range(self.retry.max_attempts):
            await self.rate_limiter.acquire()
            try:
                response = await self._client.request(
                    method, path, params=params, json=json, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if not idempotent or attempt == self.retry.max_attempts - 1:
                    raise ClientUnavailableError(
                        self._redact(f"{self.service}: {type(exc).__name__}: {exc}")
                    ) from exc
                await self._sleep(self.retry.backoff(attempt, self._rng))
                continue

            status = response.status_code
            if status < 400:
                return response
            if status in (401, 403):
                raise ClientAuthError(f"{self.service}: authentication failed ({status})")

            retriable = status in RETRY_AFTER_STATUSES or (idempotent and status in RETRIABLE_5XX)
            if retriable and attempt < self.retry.max_attempts - 1:
                delay = self._retry_after(response)
                if delay is None:
                    delay = self.retry.backoff(attempt, self._rng)
                await self._sleep(min(delay, self.retry.max_delay))
                continue
            if status >= 500:
                raise ClientUnavailableError(f"{self.service}: server error ({status})")
            raise ClientHTTPError(f"{self.service}: HTTP {status}", status)

        # Loop only exits via return/raise except when all attempts were retriable.
        raise ClientUnavailableError(
            self._redact(f"{self.service}: exhausted retries ({last_exc})")
        )

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self.request(
            method, path, params=params, json=json, headers=headers
        )
        return response.json()

    async def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return await self.request_json("GET", path, params=params)

    async def health(self) -> HealthStatus:
        """Lightweight reachability probe. Subclasses may override the path."""
        start = time.monotonic()
        try:
            await self.request("GET", self._health_path)
        except ClientAuthError as exc:
            return HealthStatus(self.service, False, str(exc))
        except ClientError as exc:
            return HealthStatus(self.service, False, self._redact(str(exc)))
        latency = (time.monotonic() - start) * 1000
        return HealthStatus(self.service, True, "reachable", round(latency, 1))
