"""Scan control endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import ScanRun, ScanStatus
from ..services.scanner import create_scan_run, run_scan
from .deps import AuthDep, get_session_factory, get_state
from .schemas import ScanRunOut, ScanStartResponse

router = APIRouter(prefix="/api", tags=["scan"], dependencies=[AuthDep])

# A RUNNING row older than this is presumed orphaned (server died mid-scan) and is
# retired instead of blocking new scans forever.
_STALE_AFTER = timedelta(minutes=30)


def _launch(request: Request, scan_run_id: int, resume: bool) -> None:
    state = get_state(request)
    task = asyncio.create_task(
        run_scan(state.settings, state.session_factory, state.hub, scan_run_id, resume=resume)
    )
    tasks: set[asyncio.Task[None]] = request.app.state.scan_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.post("/scan", response_model=ScanStartResponse, status_code=202)
async def start_scan(
    request: Request,
    resume_id: int | None = None,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ScanStartResponse:
    if resume_id is not None:
        with factory() as session:
            run = session.get(ScanRun, resume_id)
            if run is None:
                raise HTTPException(status_code=404, detail="scan run not found")
            run.status = ScanStatus.RUNNING
            session.commit()
        _launch(request, resume_id, resume=True)
        return ScanStartResponse(scan_run_id=resume_id, resume=True)

    # Idempotent start: if a scan is already underway, join it instead of racing a
    # second one (the wizard auto-starts silently; the dashboard button must not
    # double-run). Genuinely stale RUNNING rows are retired so they can't wedge us.
    with factory() as session:
        active = session.scalars(
            select(ScanRun).where(ScanRun.status == ScanStatus.RUNNING).order_by(ScanRun.id.desc())
        ).first()
        if active is not None:
            started = active.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if started is not None and datetime.now(UTC) - started < _STALE_AFTER:
                return ScanStartResponse(scan_run_id=active.id, resume=True)
            active.status = ScanStatus.INTERRUPTED
            session.commit()

    scan_run_id = create_scan_run(factory)
    _launch(request, scan_run_id, resume=False)
    return ScanStartResponse(scan_run_id=scan_run_id, resume=False)


@router.get("/scan/{scan_id}", response_model=ScanRunOut)
def get_scan(
    scan_id: int, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> ScanRun:
    with factory() as session:
        run = session.get(ScanRun, scan_id)
        if run is None:
            raise HTTPException(status_code=404, detail="scan run not found")
        session.expunge(run)
        return run


@router.get("/scan", response_model=list[ScanRunOut])
def list_scans(
    limit: int = 20, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> list[ScanRun]:
    with factory() as session:
        runs = list(
            session.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(limit))
        )
        for run in runs:
            session.expunge(run)
        return runs
