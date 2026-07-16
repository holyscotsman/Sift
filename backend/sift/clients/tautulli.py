"""Tautulli client — authoritative for watch history (plays, last-played, completion).

Tautulli exposes a single endpoint, ``/api/v2``, dispatched by a ``cmd`` query
parameter and gated by ``apikey``. Responses wrap payloads in
``{"response": {"result": "success", "data": ...}}``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import TautulliConfig
from .base import BaseClient, ClientError, HealthStatus, RateLimiter, RetryPolicy

_PAGE_SIZE = 500


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

    async def get_history(self, *, media_type: str = "movie") -> list[dict[str, Any]]:
        """Full movie watch history, paged to keep memory flat."""
        rows: list[dict[str, Any]] = []
        start = 0
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
            rows.extend(batch)
            total = int(data.get("recordsFiltered", len(rows))) if isinstance(data, dict) else 0
            start += _PAGE_SIZE
            if start >= total or not batch:
                break
        return rows
