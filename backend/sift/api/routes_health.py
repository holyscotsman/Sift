"""Health and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import junk
from ..config import Settings
from ..db.models import (
    Action,
    ActionStatus,
    Collection,
    Movie,
    MustHaveSuggestion,
    ScanRun,
    ScanStatus,
    WatchHistory,
)
from ..services.counts_cache import CountsCache
from ..services.health import HealthCache
from ..services.settings_store import effective_junk
from .deps import AuthDep, get_counts_cache, get_health_cache, get_session_factory, get_settings
from .schemas import Counts, HealthResponse, ServiceHealth, StatusResponse

router = APIRouter(prefix="/api", tags=["health"], dependencies=[AuthDep])


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
    cache: HealthCache = Depends(get_health_cache),
) -> HealthResponse:
    statuses = await cache.get(settings)
    return HealthResponse(
        services=[
            ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
            for s in statuses
        ]
    )


def _queue_counts(session: Session, settings: Settings) -> tuple[int, int]:
    # The two queues users act on. junk_flagged goes through junk.candidates so the
    # number always matches the Junk page (keep-overrides + kids-guard respected).
    thr = effective_junk(session, settings)
    junk_flagged = len(junk.candidates(session, thr, limit=10_000))
    now_owned = (
        select(Movie.tmdb_id)
        .where(Movie.in_plex.is_(True), Movie.tmdb_id == MustHaveSuggestion.tmdb_id)
        .exists()
    )
    musthave_pending = (
        session.scalar(
            select(func.count())
            .select_from(MustHaveSuggestion)
            .where(MustHaveSuggestion.status == "suggested", ~now_owned)
        )
        or 0
    )
    return junk_flagged, musthave_pending


def _counts(session: Session, settings: Settings, cache: CountsCache) -> Counts:
    """Every figure the header and dashboard show, in four statements.

    This is polled every eight seconds for as long as a tab is open, so its cost
    is not paid once — it is paid for ever. It used to issue eight separate
    ``COUNT`` statements, four of them over the same ``movies`` table with
    different filters, which on a hosted database is eight round trips and eight
    scans to answer one question. Conditional aggregates get the same four
    numbers from one pass, and the two watch figures from another.

    ``junk_flagged`` stays behind its cache because it re-scores the library;
    the rest are cheap enough to be live.
    """
    # junk_flagged re-scores the library; the dashboard polls every few seconds.
    # Cached with explicit invalidation on every write path that changes it.
    junk_flagged, musthave_pending = cache.get(lambda: _queue_counts(session, settings))

    movies, owned, monitored, upgrades = session.execute(
        select(
            func.count(),
            # "Owned" = present in your Plex library (Plex is the source of truth).
            func.count(case((Movie.in_plex.is_(True), 1))),
            func.count(case((Movie.monitored.is_(True), 1))),
            # Library titles Radarr says are below the quality cutoff.
            func.count(
                case(
                    (
                        and_(
                            Movie.in_plex.is_(True),
                            Movie.has_file.is_(True),
                            Movie.cutoff_unmet.is_(True),
                        ),
                        1,
                    )
                )
            ),
        ).select_from(Movie)
    ).one()

    # Distinct titles with any watch history is the honest "watched" numerator.
    watch_records, watched_titles = session.execute(
        select(func.count(), func.count(func.distinct(WatchHistory.movie_id))).select_from(
            WatchHistory
        )
    ).one()

    return Counts(
        junk_flagged=junk_flagged,
        musthave_pending=musthave_pending,
        movies=int(movies or 0),
        owned=int(owned or 0),
        monitored=int(monitored or 0),
        collections=session.scalar(select(func.count()).select_from(Collection)) or 0,
        watch_records=int(watch_records or 0),
        watched_titles=int(watched_titles or 0),
        actions_pending=session.scalar(
            select(func.count())
            .select_from(Action)
            .where(Action.status == ActionStatus.PROPOSED)
        )
        or 0,
        upgrades=int(upgrades or 0),
    )


@router.get("/status", response_model=StatusResponse)
def status(
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
    cache: CountsCache = Depends(get_counts_cache),
) -> StatusResponse:
    with factory() as session:
        last = session.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(1)).first()
        return StatusResponse(
            scanning=bool(last and last.status == ScanStatus.RUNNING),
            last_scan_id=last.id if last else None,
            last_scan_status=str(last.status) if last else None,
            last_scan_finished_at=last.finished_at if last else None,
            counts=_counts(session, settings, cache),
        )
