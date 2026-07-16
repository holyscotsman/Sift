"""Radarr v3 client — authoritative for the owned/monitored catalog.

Radarr is the source of truth for: what's managed, monitored/wanted, quality
profile + cutoff, TMDB collection membership, and file presence.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import RadarrConfig
from .base import BaseClient, HealthStatus, RateLimiter, RetryPolicy


class RadarrClient(BaseClient):
    def __init__(
        self,
        config: RadarrConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        super().__init__(
            "radarr",
            config.base_url,
            headers={"X-Api-Key": api_key} if api_key else None,
            retry=retry,
            rate_limiter=RateLimiter(0.0),
            secrets=[api_key] if api_key else None,
            transport=transport,
            health_path="/api/v3/system/status",
            **kwargs,
        )

    async def health(self) -> HealthStatus:
        start = time.monotonic()
        try:
            data = await self.get_json("/api/v3/system/status")
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return HealthStatus(self.service, False, self._redact(str(exc)))
        version = data.get("version", "?") if isinstance(data, dict) else "?"
        return HealthStatus(
            self.service, True, f"Radarr {version}", round((time.monotonic() - start) * 1000, 1)
        )

    async def get_movies(self) -> list[dict[str, Any]]:
        """All movies in the Radarr catalog (owned and monitored-but-missing)."""
        data = await self.get_json("/api/v3/movie")
        return list(data) if isinstance(data, list) else []

    async def get_collections(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v3/collection")
        return list(data) if isinstance(data, list) else []

    async def get_quality_profiles(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v3/qualityprofile")
        return list(data) if isinstance(data, list) else []

    async def get_root_folders(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v3/rootfolder")
        return list(data) if isinstance(data, list) else []
