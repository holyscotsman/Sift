"""TMDB v3 client — authoritative for external ratings/votes and the discovery graph.

TMDB is the candidate universe for "what's missing": collection siblings,
``similar``/``recommendations``, and shared people/keywords. It is the tightest
rate limit of the four sources, so it gets a small minimum request spacing.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import TmdbConfig
from .base import BaseClient, HealthStatus, RateLimiter, RetryPolicy

_TMDB_BASE = "https://api.themoviedb.org/3"


class TmdbClient(BaseClient):
    def __init__(
        self,
        config: TmdbConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        # A v4 bearer token (long, starts with "eyJ") goes in the Authorization
        # header; a classic v3 key goes in the query string.
        headers: dict[str, str] = {}
        params: dict[str, Any] = {"language": config.language}
        if api_key and api_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {api_key}"
        elif api_key:
            params["api_key"] = api_key
        super().__init__(
            "tmdb",
            base_url or _TMDB_BASE,
            headers=headers,
            params=params,
            retry=retry,
            rate_limiter=RateLimiter(0.03),  # ~33 req/s ceiling, well under TMDB limits
            secrets=[api_key] if api_key else None,
            transport=transport,
            health_path="/configuration",
            **kwargs,
        )

    async def health(self) -> HealthStatus:
        start = time.monotonic()
        try:
            await self.get_json("/configuration")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(self.service, False, self._redact(str(exc)))
        return HealthStatus(
            self.service, True, "reachable", round((time.monotonic() - start) * 1000, 1)
        )

    async def get_movie(
        self, tmdb_id: int, *, append: str = "keywords,credits"
    ) -> dict[str, Any]:
        data: dict[str, Any] = await self.get_json(
            f"/movie/{tmdb_id}", params={"append_to_response": append}
        )
        return data

    async def get_collection(self, collection_id: int) -> dict[str, Any]:
        data: dict[str, Any] = await self.get_json(f"/collection/{collection_id}")
        return data

    async def get_similar(self, tmdb_id: int, *, page: int = 1) -> list[dict[str, Any]]:
        data = await self.get_json(f"/movie/{tmdb_id}/similar", params={"page": page})
        return list(data.get("results", [])) if isinstance(data, dict) else []

    async def get_recommendations(self, tmdb_id: int, *, page: int = 1) -> list[dict[str, Any]]:
        data = await self.get_json(f"/movie/{tmdb_id}/recommendations", params={"page": page})
        return list(data.get("results", [])) if isinstance(data, dict) else []
