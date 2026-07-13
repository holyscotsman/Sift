"""Scan control endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import ScanRun, ScanStatus
from ..services.scanner import create_scan_run, run_scan
from .deps import AuthDep, get_session_factory, get_state
from .schemas import ScanRunOut, ScanStartResponse

router = APIRouter(prefix="/api", tags=["scan"], dependencies=[AuthDep])


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
