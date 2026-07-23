"""Automatic rescans on a user-chosen interval (Settings › Autonomy).

A light poller wakes every 15 minutes and starts a scan when all of these hold:
an interval is configured, Plex is connected, no scan is currently running in
this process, and the last completed scan finished longer ago than the interval.
The anchor is the last *completed* scan's ``finished_at`` — no extra state, so
restarts can't drift the schedule.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ScanRun, ScanStatus
from ..db.session import in_thread
from . import settings_store
from .scanner import create_scan_run, launch_scan

log = logging.getLogger("sift.autoscan")

CHECK_SECONDS = 15 * 60


def is_due(session: Session, interval_hours: int, now: datetime) -> bool:
    """Due when the last completed scan is older than the interval (or none exists)."""
    last = session.scalars(
        select(ScanRun)
        .where(ScanRun.status == ScanStatus.COMPLETED)
        .order_by(ScanRun.id.desc())
    ).first()
    if last is None or last.finished_at is None:
        return True
    finished = last.finished_at
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    return now - finished >= timedelta(hours=interval_hours)


async def tick(app: Any) -> int | None:
    """One schedule check. Returns the started scan id, or None."""
    state = app.state.sift
    interval = await in_thread(state.session_factory, settings_store.get_scan_interval)
    if interval <= 0:
        return None
    if getattr(app.state, "active_scans", set()):
        return None  # a scan is already running — never double-run
    settings = state.settings
    if not settings.plex.enabled or not settings.plex.base_url:
        return None  # nothing to scan yet
    due = await in_thread(
        state.session_factory, lambda s: is_due(s, interval, datetime.now(UTC))
    )
    if not due:
        return None
    scan_id = create_scan_run(state.session_factory)
    launch_scan(app, scan_id)
    log.info("autoscan: started scan %s (every %sh)", scan_id, interval)
    return scan_id


async def loop(app: Any, *, check_seconds: int = CHECK_SECONDS) -> None:
    """Run forever; every tick is individually guarded so one failure never kills
    the schedule."""
    while True:
        await asyncio.sleep(check_seconds)
        try:
            await tick(app)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep the schedule alive
            log.warning("autoscan tick failed: %s", exc)
