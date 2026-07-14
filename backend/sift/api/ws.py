"""In-memory scan-progress pub/sub and the ``/ws/scan/{id}`` endpoint."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..ingest.pipeline import ScanProgress
from .deps import token_accepted

router = APIRouter()

_QUEUE_MAX = 100


class ScanHub:
    """Fan-out of scan progress events to any connected WebSocket subscribers."""

    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, scan_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subs.setdefault(scan_id, set()).add(queue)
        return queue

    def unsubscribe(self, scan_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subs.get(scan_id)
        if subs:
            subs.discard(queue)
            if not subs:
                self._subs.pop(scan_id, None)

    async def publish(self, scan_id: int, message: dict[str, Any]) -> None:
        for queue in list(self._subs.get(scan_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    async def publish_progress(self, progress: ScanProgress) -> None:
        await self.publish(progress.scan_run_id, {"event": "progress", **asdict(progress)})


@router.websocket("/ws/scan/{scan_id}")
async def scan_ws(
    websocket: WebSocket, scan_id: int, token: str | None = Query(default=None)
) -> None:
    state = websocket.app.state.sift
    # Same auth as the REST gate: a login session token or the static API token.
    # (Previously only the static token was accepted, so progress silently dropped
    # for logged-in users on a token-configured deploy.)
    if not token_accepted(state, token):
        await websocket.close(code=4401)
        return
    hub: ScanHub = state.hub
    queue = hub.subscribe(scan_id)
    await websocket.accept()
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("event") == "terminal":
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(scan_id, queue)
