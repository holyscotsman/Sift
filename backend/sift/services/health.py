"""Per-service connection health.

Builds the enabled clients from settings, probes each concurrently, and returns a
uniform list of :class:`~sift.clients.base.HealthStatus`. Disabled services report
``ok=False`` with a ``disabled`` detail rather than being silently dropped, so the
UI can show every configured source.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ..clients.base import BaseClient, ClientError, HealthStatus
from ..clients.plex import PlexClient
from ..clients.radarr import RadarrClient
from ..clients.tautulli import TautulliClient
from ..clients.tmdb import TmdbClient
from ..config import Settings

_SERVICES = ("plex", "radarr", "tautulli", "tmdb")
# Each client takes its own config model, so the factory type is a plain callable.
_CLIENT_TYPES: dict[str, Callable[[Any], BaseClient]] = {
    "plex": PlexClient,
    "radarr": RadarrClient,
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


def _ai_health() -> HealthStatus:
    from ..ai.registry import ai_configured

    ok = ai_configured()
    return HealthStatus("model", ok, "Anthropic" if ok else "not configured")


async def gather_health(settings: Settings) -> list[HealthStatus]:
    statuses = list(await asyncio.gather(*(_probe(settings, s) for s in _SERVICES)))
    statuses.append(_ai_health())
    return statuses


async def check_service(settings: Settings, service: str) -> HealthStatus:
    if service not in _SERVICES:
        raise ValueError(f"unknown service {service!r}")
    return await _probe(settings, service)
