"""Tautulli client — authoritative for watch history (plays, last-played, completion).

Tautulli exposes a single endpoint, ``/api/v2``, dispatched by a ``cmd`` query
parameter and gated by ``apikey``. Responses wrap payloads in
``{"response": {"result": "success", "data": ...}}``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import TautulliConfig
from .base import BaseClient, ClientError, HealthStatus, RateLimiter, RetryPolicy

log = logging.getLogger("sift.tautulli")

_PAGE_SIZE = 500

# Backstop on a history sweep: 2000 pages is a million plays, far beyond any real
# household and small enough that a misbehaving server costs minutes.
_MAX_PAGES = 2000


class TautulliClient(BaseClient):
    def __init__(
        self,
        config: TautulliConfig,
        *,
        retry: RetryPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        api_key = config.api_key.get_secret_value() if config.api_key else None
        super().__init__(
            "tautulli",
            config.base_url,
            params={"apikey": api_key} if api_key else None,
            retry=retry,
            rate_limiter=RateLimiter(0.0),
            secrets=[api_key] if api_key else None,
            transport=transport,
            **kwargs,
        )

    async def _cmd(self, cmd: str, **params: Any) -> Any:
        """Call a Tautulli command and unwrap ``response.data``."""
        payload = await self.get_json("/api/v2", params={"cmd": cmd, **params})
        response = payload.get("response", {}) if isinstance(payload, dict) else {}
        if response.get("result") != "success":
            raise ClientError(f"tautulli: cmd {cmd} failed: {response.get('message')}")
        return response.get("data")

    async def health(self) -> HealthStatus:
        start = time.monotonic()
        try:
            await self._cmd("get_server_info")
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(self.service, False, self._redact(str(exc)))
        return HealthStatus(
            self.service, True, "reachable", round((time.monotonic() - start) * 1000, 1)
        )

    async def get_users(self) -> list[dict[str, Any]]:
        data = await self._cmd("get_users")
        return list(data) if isinstance(data, list) else []

    async def iter_history(
        self, *, media_type: str = "movie"
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield watch history a page at a time.

        History is the one source whose size tracks how much television gets
        watched rather than how much of it is owned, so a heavy household's
        episode history dwarfs its library. Everything downstream folds it into
        per-title aggregates, which means no caller ever needs the whole thing in
        memory — and holding it anyway is how a phase gets killed on a small host.
        """
        start = 0
        seen = 0
        pages = 0
        while True:
            data = await self._cmd(
                "get_history",
                media_type=media_type,
                length=_PAGE_SIZE,
                start=start,
                order_column="date",
                order_dir="desc",
            )
            batch = list(data.get("data", [])) if isinstance(data, dict) else []
            if not batch:
                return
            yield batch

            total = int(data.get("recordsFiltered", 0)) if isinstance(data, dict) else 0
            start += _PAGE_SIZE
            seen += len(batch)
            pages += 1
            if start >= total:
                return
            # The same two floors the Plex sweep carries, for the same reason: a
            # server that ignores start/length answers every page with the first
            # one, and without these the read never ends.
            if seen >= total:
                log.warning("tautulli ignored pagination — stopping after %s rows", seen)
                return
            if pages >= _MAX_PAGES:
                log.warning("tautulli history exceeded %s pages — stopping", _MAX_PAGES)
                return

    async def get_history(self, *, media_type: str = "movie") -> list[dict[str, Any]]:
        """The whole history at once. Prefer :meth:`iter_history` for a scan."""
        rows: list[dict[str, Any]] = []
        async for batch in self.iter_history(media_type=media_type):
            rows.extend(batch)
        return rows
