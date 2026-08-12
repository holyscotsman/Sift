"""Sonarr v3 client — authoritative for the TV catalog and its files.

The division of labour mirrors Radarr's: Plex says what is *in the library*,
Sonarr says what each episode's file actually *is* — its size, quality, and the
media detail the bitrate baselines need — and is where a decision gets written
back so it sticks.

Two calls carry most of the weight. ``get_series`` returns per-season
``statistics.sizeOnDisk`` and episode counts for the whole library in one request,
which answers "which show is heaviest" with no per-episode work at all. Only the
shows worth looking at closely need ``get_episode_files``, which is a request per
series.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import SonarrConfig
from .base import BaseClient, HealthStatus, RateLimiter, RetryPolicy


class SonarrClient(BaseClient):
    def __init__(
        self,
        config: SonarrConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        super().__init__(
            "sonarr",
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
            self.service, True, f"Sonarr {version}", round((time.monotonic() - start) * 1000, 1)
        )

    async def get_series(self) -> list[dict[str, Any]]:
        """Every series, with per-season statistics. One request for the library."""
        data = await self.get_json("/api/v3/series")
        return list(data) if isinstance(data, list) else []

    async def get_episodes(self, series_id: int) -> list[dict[str, Any]]:
        """Every episode of one series, including which file backs it.

        ``episodeFileId`` is what makes duplicate detection exact: a single
        "S01E01-E02" file is one file covering two episodes, and Sonarr gives both
        episodes the same id — so a shared id is a multi-episode file rather than
        a duplicate, with no guessing from filenames.
        """
        data = await self.get_json("/api/v3/episode", params={"seriesId": series_id})
        return list(data) if isinstance(data, list) else []

    async def get_episode_files(self, series_id: int) -> list[dict[str, Any]]:
        """Every episode file of one series, with size and media detail."""
        data = await self.get_json("/api/v3/episodefile", params={"seriesId": series_id})
        return list(data) if isinstance(data, list) else []

    async def get_quality_profiles(self) -> list[dict[str, Any]]:
        data = await self.get_json("/api/v3/qualityprofile")
        return list(data) if isinstance(data, list) else []
