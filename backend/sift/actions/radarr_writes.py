"""Dry-run-capable Radarr write wrapper.

Every mutating call to Radarr goes through here. In ``dry_run`` mode the intended
request is logged and returned but **never sent** — nothing changes on the server.
The delete path is exposed but is only ever reached via ``ActionEngine`` after an
approval (the golden safety rule); this wrapper additionally logs deletes loudly.

A live write builds a short-lived :class:`RadarrClient` from the stored
:class:`RadarrConfig`, sends the one request, and closes it. Deletes/monitors are
rare and user-driven, so a per-write client (rather than a long-lived pooled one)
keeps the lifecycle trivial — nothing to dispose at shutdown. Passing ``None`` for
the config yields a writer that can *stage* (dry-run) but refuses any live write;
that is the shape the test ``SpyWriter`` subclasses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..clients.radarr import RadarrClient
from ..config import RadarrConfig

log = logging.getLogger("sift.actions")


@dataclass
class WriteResult:
    method: str
    path: str
    payload: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    sent: bool = False
    response: Any = None


class RadarrWriter:
    def __init__(
        self,
        config: RadarrConfig | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        # Test seam: injected into the per-write RadarrClient so live writes can be
        # exercised against a mock server without real network I/O.
        self._transport = transport

    def _live_capable(self) -> bool:
        """True when a real request could actually be issued (config + base_url)."""
        return self._config is not None and bool(self._config.base_url)

    async def _execute(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, dry_run: bool = True,
    ) -> WriteResult:
        payload = {"params": params or {}, "json": json or {}}
        if dry_run:
            log.info("DRY-RUN %s %s payload=%s", method, path, payload)
            return WriteResult(method, path, payload, dry_run=True, sent=False)
        if not self._live_capable():
            raise RuntimeError(
                "RadarrWriter has no Radarr connection configured for a live write"
            )
        if self._config is None:  # narrowed by _live_capable; explicit for -O runs
            raise RuntimeError("no Radarr config for a live write")
        async with RadarrClient(self._config, transport=self._transport) as client:
            response = await client.request(method, path, params=params, json=json)
        return WriteResult(
            method, path, payload, dry_run=False, sent=True, response=response.status_code
        )

    async def add_movie(self, payload: dict[str, Any], *, dry_run: bool = True) -> WriteResult:
        return await self._execute("POST", "/api/v3/movie", json=payload, dry_run=dry_run)

    async def set_monitored(
        self, movie_id: int, monitored: bool, *, dry_run: bool = True
    ) -> WriteResult:
        body = {"movieIds": [movie_id], "monitored": monitored}
        return await self._execute("PUT", "/api/v3/movie/editor", json=body, dry_run=dry_run)

    async def delete_movie(
        self, movie_id: int, *, delete_files: bool, dry_run: bool = True
    ) -> WriteResult:
        # This is the irreversible path when delete_files is True. It must only ever
        # be called by ActionEngine after an approval — see actions/engine.py.
        if delete_files and not dry_run:
            log.warning("ISSUING FILE DELETE for radarr movie %s (irreversible)", movie_id)
        return await self._execute(
            "DELETE",
            f"/api/v3/movie/{movie_id}",
            params={"deleteFiles": str(delete_files).lower(), "addImportExclusion": "false"},
            dry_run=dry_run,
        )
