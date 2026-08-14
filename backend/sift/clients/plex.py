"""Plex client — authoritative for what's playable and kids-vs-adult separation.

Plex uses a token (``X-Plex-Token``) and, with an ``Accept: application/json``
header, returns JSON ``MediaContainer`` documents. Movie library items are paged
through with ``X-Plex-Container-Start`` / ``X-Plex-Container-Size``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import PlexConfig
from .base import BaseClient, HealthStatus, RateLimiter, RetryPolicy

log = logging.getLogger("sift.plex")

_PAGE_SIZE = 200

# Backstop on a section sweep. 2000 pages is 400,000 items — far beyond any real
# library, and small enough that a server misbehaving costs minutes rather than
# the whole scan.
_MAX_PAGES = 2000

# Plex's library item types. A show section holds all three; which one you ask for
# decides what comes back.
MOVIE = 1
SHOW = 2
EPISODE = 4


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
        # How many items the last section sweep said it held. Read from Plex's own
        # MediaContainer, so it is a real denominator rather than a guess — the
        # scan uses it to report how far through a long phase it is.
        self.last_section_total = 0

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

    async def iter_section_items(
        self, section_key: str | int, *, item_type: int = MOVIE
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield a section's items a page at a time.

        A generator rather than a list because an episode sweep over a large TV
        library is tens of thousands of records carrying full media metadata.
        Holding all of that before writing anything is how a scan gets killed for
        memory on a small host — and a killed process leaves the run marked
        running forever, which reads as a scan stuck at the same percentage.
        """
        start = 0
        seen = 0
        pages = 0
        while True:
            data = await self.request_json(
                "GET",
                f"/library/sections/{section_key}/all",
                params={"type": item_type, "includeGuids": 1},
                headers={
                    "X-Plex-Container-Start": str(start),
                    "X-Plex-Container-Size": str(_PAGE_SIZE),
                },
            )
            container = data.get("MediaContainer", {}) if isinstance(data, dict) else {}
            batch = list(container.get("Metadata", []))
            if not batch:
                return
            yield batch

            total = int(container.get("totalSize", container.get("size", len(batch))))
            self.last_section_total = total
            start += _PAGE_SIZE
            seen += len(batch)
            pages += 1
            if start >= total:
                return
            # Two independent floors. A server that ignores the container headers
            # returns the whole section every time, so the page count never
            # advances and the loop would run until memory ran out; either of
            # these turns that into a bounded read of whatever it did return.
            if seen >= total:
                log.warning(
                    "plex section %s ignored pagination — stopping after %s items",
                    section_key,
                    seen,
                )
                return
            if pages >= _MAX_PAGES:
                log.warning("plex section %s exceeded %s pages — stopping", section_key, _MAX_PAGES)
                return

    async def get_section_items(
        self, section_key: str | int, *, item_type: int = MOVIE
    ) -> list[dict[str, Any]]:
        """All items of one type in a section, paged to keep memory flat.

        ``item_type`` selects the level to read: a show section holds shows,
        seasons and episodes, and asking for episodes directly returns them flat
        across the whole section rather than requiring a walk down the tree.
        """
        items: list[dict[str, Any]] = []
        async for batch in self.iter_section_items(section_key, item_type=item_type):
            items.extend(batch)
        return items
