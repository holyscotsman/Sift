"""Per-service connection health.

Builds the enabled clients from settings, probes each concurrently, and returns a
uniform list of :class:`~sift.clients.base.HealthStatus`. Disabled services report
``ok=False`` with a ``disabled`` detail rather than being silently dropped, so the
UI can show every configured source.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ..clients.base import BaseClient, ClientError, HealthStatus
from ..clients.overseerr import OverseerrClient
from ..clients.plex import PlexClient
from ..clients.radarr import RadarrClient
from ..clients.tautulli import TautulliClient
from ..clients.tmdb import TmdbClient
from ..config import Settings

_SERVICES = ("plex", "radarr", "overseerr", "tautulli", "tmdb")
# Each client takes its own config model, so the factory type is a plain callable.
_CLIENT_TYPES: dict[str, Callable[[Any], BaseClient]] = {
    "plex": PlexClient,
    "radarr": RadarrClient,
    "overseerr": OverseerrClient,
    "tautulli": TautulliClient,
    "tmdb": TmdbClient,
}


def build_client(settings: Settings, service: str) -> BaseClient | None:
    """Instantiate a configured client, or ``None`` if it lacks a base_url."""
    cfg = getattr(settings, service)
    try:
        return _CLIENT_TYPES[service](cfg)
    except ClientError:
        return None  # base_url not configured


async def _probe(settings: Settings, service: str) -> HealthStatus:
    cfg = getattr(settings, service)
    if not cfg.enabled:
        return HealthStatus(service, False, "disabled")
    client = build_client(settings, service)
    if client is None:
        return HealthStatus(service, False, "not configured")
    try:
        return await client.health()
    finally:
        await client.aclose()


def _ai_health(settings: Settings) -> HealthStatus:
    from ..ai.registry import ai_configured

    ok = ai_configured(settings)
    return HealthStatus("model", ok, "Anthropic" if ok else "not configured")


async def gather_health(settings: Settings) -> list[HealthStatus]:
    statuses = list(await asyncio.gather(*(_probe(settings, s) for s in _SERVICES)))
    statuses.append(_ai_health(settings))
    return statuses


async def check_service(settings: Settings, service: str) -> HealthStatus:
    if service not in _SERVICES:
        raise ValueError(f"unknown service {service!r}")
    return await _probe(settings, service)


class HealthCache:
    """Short-lived cache for the full health sweep. The dashboard polls health
    every 20 s and /api/settings probes the same hosts — with a dead host
    configured, every poll rides a timeout for nothing. 15 s keeps the UI at
    most one poll stale; saving or testing a connection invalidates so a fixed
    URL shows up immediately (the per-service *test* endpoints always probe
    live, never this cache)."""

    def __init__(self, ttl_seconds: float = 15.0) -> None:
        self._ttl = ttl_seconds
        self._value: list[HealthStatus] | None = None
        self._at = 0.0

    async def get(self, settings: Settings) -> list[HealthStatus]:
        now = time.monotonic()
        if self._value is not None and now - self._at < self._ttl:
            return self._value
        self._value = await gather_health(settings)
        self._at = now
        return self._value

    def invalidate(self) -> None:
        self._value = None
