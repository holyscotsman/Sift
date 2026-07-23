"""Scan control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import ScanRun, ScanStatus
from ..services.scanner import create_scan_run, launch_scan
from .deps import AuthDep, get_session_factory
from .schemas import ScanRunOut, ScanStartResponse

router = APIRouter(prefix="/api", tags=["scan"], dependencies=[AuthDep])


def _active_scans(request: Request) -> set[int]:
    """Scan-run ids with a live task in THIS process — exact liveness, no age
    heuristics (a big library can legitimately scan for hours)."""
    active: set[int] = getattr(request.app.state, "active_scans", set())
    return active


def _launch(request: Request, scan_run_id: int, resume: bool) -> None:
    launch_scan(request.app, scan_run_id, resume=resume)


@router.post("/scan", response_model=ScanStartResponse, status_code=202)
async def start_scan(
    request: Request,
    resume_id: int | None = None,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ScanStartResponse:
    live = _active_scans(request)

    if resume_id is not None:
        if resume_id in live:
            # Already running right here — resuming it again would race itself.
            return ScanStartResponse(scan_run_id=resume_id, resume=True)
        if live:
            raise HTTPException(status_code=409, detail="another scan is already running")
        with factory() as session:
            run = session.get(ScanRun, resume_id)
            if run is None:
                raise HTTPException(status_code=404, detail="scan run not found")
            run.status = ScanStatus.RUNNING
            session.commit()
        _launch(request, resume_id, resume=True)
        return ScanStartResponse(scan_run_id=resume_id, resume=True)

    # Idempotent start: if a scan is already underway in this process, join it
    # instead of racing a second one (the wizard auto-starts silently; the dashboard
    # button must not double-run). A RUNNING row with no live task is an orphan from
    # a dead process — retire it so it can't wedge scanning forever.
    with factory() as session:
        running = session.scalars(
            select(ScanRun).where(ScanRun.status == ScanStatus.RUNNING).order_by(ScanRun.id.desc())
        ).all()
        for row in running:
            if row.id in live:
                return ScanStartResponse(scan_run_id=row.id, resume=True)
            row.status = ScanStatus.INTERRUPTED
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
