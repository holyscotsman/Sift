"""Build the enabled clients, run a scan, and stream progress to the hub.

This is the glue between the HTTP layer (which owns the ``ScanRun`` row and the
WebSocket hub) and the pure ``ScanPipeline``. Clients are created per-scan and
always closed, even on failure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from ..clients.base import BaseClient, ClientError
from ..clients.plex import PlexClient
from ..clients.radarr import RadarrClient
from ..clients.tautulli import TautulliClient
from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import ScanRun, ScanStatus
from ..ingest.pipeline import ScanPipeline, ScanProgress

log = logging.getLogger("sift.scanner")


class ProgressHub(Protocol):
    """Structural type for anything the scanner can stream progress to."""

    async def publish(self, scan_id: int, message: dict[str, Any]) -> None: ...
    async def publish_progress(self, progress: ScanProgress) -> None: ...


def create_scan_run(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        run = ScanRun(status=ScanStatus.RUNNING)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def launch_scan(app: Any, scan_run_id: int, *, resume: bool = False) -> None:
    """Start a scan task and register it for exact liveness tracking. The single
    launcher used by the HTTP route and the auto-rescan loop, so `active_scans`
    can never disagree with reality."""
    import asyncio

    state = app.state.sift
    task = asyncio.create_task(
        run_scan(state.settings, state.session_factory, state.hub, scan_run_id, resume=resume)
    )
    tasks: set[asyncio.Task[None]] = app.state.scan_tasks
    tasks.add(task)
    active: set[int] = getattr(app.state, "active_scans", set())
    active.add(scan_run_id)
    app.state.active_scans = active

    def _done(t: asyncio.Task[None]) -> None:
        tasks.discard(t)
        active.discard(scan_run_id)
        # A finished scan (however it ended) may have changed both status queues.
        state.counts_cache.invalidate()

    task.add_done_callback(_done)


def _maybe_client[C: BaseClient](
    settings: Settings, service: str, cls: Callable[[Any], C]
) -> C | None:
    cfg = getattr(settings, service)
    if not cfg.enabled:
        return None
    try:
        return cls(cfg)
    except ClientError:
        log.info("%s disabled: not configured", service)
        return None


async def run_scan(
    settings: Settings,
    factory: sessionmaker[Session],
    hub: ProgressHub,
    scan_run_id: int,
    *,
    resume: bool = False,
) -> None:
    radarr = _maybe_client(settings, "radarr", RadarrClient)
    plex = _maybe_client(settings, "plex", PlexClient)
    tautulli = _maybe_client(settings, "tautulli", TautulliClient)
    tmdb = _maybe_client(settings, "tmdb", TmdbClient)
    pipeline = ScanPipeline(
        factory,
        settings,
        radarr=radarr,
        plex=plex,
        tautulli=tautulli,
        tmdb=tmdb,
        progress_cb=hub.publish_progress,
        tmdb_enrich_limit=settings.tmdb.enrich_limit,
    )
    try:
        run = await pipeline.run(scan_run_id, resume=resume)
        await hub.publish(
            scan_run_id, {"event": "terminal", "status": str(run.status), "stats": run.stats}
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to subscribers, not swallowed
        log.warning("scan %s failed: %s", scan_run_id, exc)
        await hub.publish(
            scan_run_id, {"event": "terminal", "status": "interrupted", "error": str(exc)}
        )
    finally:
        for client in (radarr, plex, tautulli, tmdb):
            if client is not None:
                await client.aclose()
