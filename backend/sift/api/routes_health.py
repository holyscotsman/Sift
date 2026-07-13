"""Health and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db.models import Action, ActionStatus, Collection, Movie, ScanRun, ScanStatus, WatchHistory
from ..services.health import gather_health
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import Counts, HealthResponse, ServiceHealth, StatusResponse

router = APIRouter(prefix="/api", tags=["health"], dependencies=[AuthDep])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    statuses = await gather_health(settings)
    return HealthResponse(
        services=[
            ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
            for s in statuses
        ]
    )


def _counts(session: Session) -> Counts:
    return Counts(
        movies=session.scalar(select(func.count()).select_from(Movie)) or 0,
        # "Owned" = present in your Plex library (Plex is the source of truth).
        owned=session.scalar(
            select(func.count()).select_from(Movie).where(Movie.in_plex.is_(True))
        )
        or 0,
        monitored=session.scalar(
            select(func.count()).select_from(Movie).where(Movie.monitored.is_(True))
        )
        or 0,
        collections=session.scalar(select(func.count()).select_from(Collection)) or 0,
        watch_records=session.scalar(select(func.count()).select_from(WatchHistory)) or 0,
        actions_pending=session.scalar(
            select(func.count())
            .select_from(Action)
            .where(Action.status == ActionStatus.PROPOSED)
        )
        or 0,
    )


@router.get("/status", response_model=StatusResponse)
def status(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> StatusResponse:
    with factory() as session:
        last = session.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(1)).first()
        return StatusResponse(
            scanning=bool(last and last.status == ScanStatus.RUNNING),
            last_scan_id=last.id if last else None,
            last_scan_status=str(last.status) if last else None,
            last_scan_finished_at=last.finished_at if last else None,
            counts=_counts(session),
        )
