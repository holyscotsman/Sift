"""Plex client — authoritative for what's playable and kids-vs-adult separation.

Plex uses a token (``X-Plex-Token``) and, with an ``Accept: application/json``
header, returns JSON ``MediaContainer`` documents. Movie library items are paged
through with ``X-Plex-Container-Start`` / ``X-Plex-Container-Size``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import PlexConfig
from .base import BaseClient, HealthStatus, RateLimiter, RetryPolicy

_PAGE_SIZE = 200


class PlexClient(BaseClient):
    def __init__(
        self,
        config: PlexConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        token = config.token.get_secret_value() if config.token else None
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Plex-Token"] = token
        super().__init__(
            "plex",
            config.base_url,
            headers=headers,
            retry=retry,
            rate_limiter=RateLimiter(0.0),
            secrets=[token] if token else None,
            transport=transport,
            health_path="/identity",
            **kwargs,
        )

    async def health(self) -> HealthStatus:
        start = time.monotonic()
        try:
            data = await self.get_json("/identity")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(self.service, False, self._redact(str(exc)))
        container = data.get("MediaContainer", {}) if isinstance(data, dict) else {}
        version = container.get("version", "?")
        return HealthStatus(
            self.service, True, f"Plex {version}", round((time.monotonic() - start) * 1000, 1)
        )

    async def get_sections(self) -> list[dict[str, Any]]:
        """Library sections (Directory entries). Movie sections have ``type == 'movie'``."""
        data = await self.get_json("/library/sections")
        container = data.get("MediaContainer", {}) if isinstance(data, dict) else {}
        return list(container.get("Directory", []))

    async def get_section_items(self, section_key: str | int) -> list[dict[str, Any]]:
        """All items in a section, paged to keep memory flat on large libraries."""
        items: list[dict[str, Any]] = []
        start = 0
        while True:
            data = await self.request_json(
                "GET",
                f"/library/sections/{section_key}/all",
                headers={
                    "X-Plex-Container-Start": str(start),
                    "X-Plex-Container-Size": str(_PAGE_SIZE),
                },
            )
            container = data.get("MediaContainer", {}) if isinstance(data, dict) else {}
            batch = list(container.get("Metadata", []))
            items.extend(batch)
            total = int(container.get("totalSize", container.get("size", len(batch))))
            start += _PAGE_SIZE
            if start >= total or not batch:
                break
        return items
