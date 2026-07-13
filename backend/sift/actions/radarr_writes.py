"""Dry-run-capable Radarr write wrapper.

Every mutating call to Radarr goes through here. In ``dry_run`` mode the intended
request is logged and returned but **never sent** — nothing changes on the server.
The delete path is exposed but is only ever reached via ``ActionEngine`` after an
approval (the golden safety rule); this wrapper additionally logs deletes loudly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..clients.radarr import RadarrClient

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
    def __init__(self, client: RadarrClient | None) -> None:
        self._client = client

    async def _execute(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None, dry_run: bool = True,
    ) -> WriteResult:
        payload = {"params": params or {}, "json": json or {}}
        if dry_run:
            log.info("DRY-RUN %s %s payload=%s", method, path, payload)
            return WriteResult(method, path, payload, dry_run=True, sent=False)
        if self._client is None:
            raise RuntimeError("RadarrWriter has no client configured for a live write")
        response = await self._client.request(method, path, params=params, json=json)
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
