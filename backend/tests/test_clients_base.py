"""Retry/backoff, rate limiting, and secret redaction in the client base."""

from __future__ import annotations

import httpx
import pytest

from sift.clients.base import (
    BaseClient,
    ClientAuthError,
    ClientHTTPError,
    ClientUnavailableError,
    RateLimiter,
    RetryPolicy,
)


async def _noop_sleep(_seconds: float) -> None:
    return None


def _client(handler, *, secrets=None) -> BaseClient:
    return BaseClient(
        "test",
        "http://svc.local",
        transport=httpx.MockTransport(handler),
        retry=RetryPolicy(max_attempts=4, jitter=False, base_delay=0.0),
        sleep=_noop_sleep,
        secrets=secrets,
    )


async def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    body = await client.get_json("/x")
    assert body == {"ok": True}
    assert calls["n"] == 3
    await client.aclose()


async def test_get_500_retries_to_exhaustion():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(ClientUnavailableError):
        await client.get_json("/x")
    assert calls["n"] == 4  # max_attempts
    await client.aclose()


async def test_post_500_does_not_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)

    client = _client(handler)
    with pytest.raises(ClientUnavailableError):
        await client.request("POST", "/x", json={"a": 1})
    # NEGATIVE CONTROL: a non-idempotent POST must NOT be retried on a 500.
    assert calls["n"] == 1
    await client.aclose()


async def test_auth_error_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401)

    client = _client(handler)
    with pytest.raises(ClientAuthError):
        await client.get_json("/x")
    assert calls["n"] == 1
    await client.aclose()


async def test_404_raises_http_error():
    client = _client(lambda request: httpx.Response(404))
    with pytest.raises(ClientHTTPError) as exc:
        await client.get_json("/missing")
    assert exc.value.status_code == 404
    await client.aclose()


async def test_secret_is_redacted_in_errors():
    def handler(request):
        raise httpx.ConnectError("cannot reach http://svc.local?token=SEKRET")

    client = _client(handler, secrets=["SEKRET"])
    with pytest.raises(ClientUnavailableError) as exc:
        await client.get_json("/x")
    assert "SEKRET" not in str(exc.value)
    assert "***" in str(exc.value)
    await client.aclose()


async def test_rate_limiter_spaces_requests():
    now = {"t": 0.0}
    slept = []

    def clock() -> float:
        return now["t"]

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now["t"] += seconds

    limiter = RateLimiter(0.5, clock=clock, sleep=sleep)
    await limiter.acquire()  # first is free
    await limiter.acquire()  # second must wait ~0.5
    assert slept and abs(slept[0] - 0.5) < 1e-9


async def test_no_wait_when_interval_zero():
    slept = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    limiter = RateLimiter(0.0, sleep=sleep)
    await limiter.acquire()
    await limiter.acquire()
    assert slept == []
