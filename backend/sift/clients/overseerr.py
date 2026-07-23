"""Overseerr client — the preferred front door for add-requests.

When Overseerr is configured, "add this movie" becomes an Overseerr *request*
(flowing through its own approval/quality pipeline) instead of a direct Radarr
add. Only two calls are needed: a status probe and the request itself.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import OverseerrConfig
from .base import BaseClient, RetryPolicy


class OverseerrClient(BaseClient):
    def __init__(
        self,
        config: OverseerrConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        super().__init__(
            "overseerr",
            config.base_url,
            headers={"X-Api-Key": api_key} if api_key else None,
            secrets=[api_key] if api_key else None,
            retry=retry,
            transport=transport,
            **kwargs,
        )
        self._health_path = "/api/v1/status"

    async def request_movie(self, tmdb_id: int) -> dict[str, Any]:
        """File a movie request. Overseerr resolves quality/root itself, and its
        own settings decide whether the request needs manual approval."""
        data: dict[str, Any] = await self.request_json(
            "POST", "/api/v1/request", json={"mediaType": "movie", "mediaId": tmdb_id}
        )
        return data
