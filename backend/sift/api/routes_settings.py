"""Settings: connection status, editable scoring thresholds (with live preview),
and the automatic-rescan schedule."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from ..ai.registry import ai_configured
from ..analysis import junk
from ..config import JunkThresholds, Settings
from ..services import curated_lists, settings_store
from ..services.counts_cache import CountsCache
from ..services.health import HealthCache, check_service
from .deps import AuthDep, get_counts_cache, get_health_cache, get_session_factory, get_settings
from .schemas import (
    ScanScheduleIn,
    ScanScheduleOut,
    ServiceHealth,
    SettingsResponse,
    ThresholdPreview,
    ThresholdsModel,
)

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[AuthDep])


def _thresholds_out(thr: JunkThresholds) -> ThresholdsModel:
    return ThresholdsModel(
        min_votes=thr.min_votes,
        rating_floor=thr.rating_floor,
        unwatched_years=thr.unwatched_years,
        junk_cutoff=thr.junk_cutoff,
        borderline_cutoff=thr.borderline_cutoff,
    )


def _merged(base: JunkThresholds, body: ThresholdsModel) -> JunkThresholds:
    return JunkThresholds(**{**base.model_dump(), **body.model_dump()})


@router.get("", response_model=SettingsResponse)
async def get_all(
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
    health_cache: HealthCache = Depends(get_health_cache),
) -> SettingsResponse:
    health = await health_cache.get(settings)
    with factory() as session:
        thr = settings_store.effective_junk(session, settings)
        interval = settings_store.get_scan_interval(session)
    db_kind = "postgres" if settings.database.target().startswith("postgres") else "sqlite"
    return SettingsResponse(
        connections=[
            ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
            for s in health
        ],
        thresholds=_thresholds_out(thr),
        ai_configured=ai_configured(settings),
        actions_dry_run=settings.actions.dry_run,
        database_kind=db_kind,
        # SQLite on Render's free tier lives on an ephemeral disk: login + config
        # vanish on every redeploy. Render sets the RENDER env var, so warn there.
        ephemeral_risk=db_kind == "sqlite" and bool(os.environ.get("RENDER")),
        scan_interval_hours=interval,
    )


@router.put("/scan_schedule", response_model=ScanScheduleOut)
def save_scan_schedule(
    body: ScanScheduleIn,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ScanScheduleOut:
    try:
        with factory() as session:
            hours = settings_store.set_scan_interval(session, body.interval_hours)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScanScheduleOut(interval_hours=hours)


@router.post("/thresholds/preview", response_model=ThresholdPreview)
def preview(
    body: ThresholdsModel,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> ThresholdPreview:
    counts = junk.preview(factory, _merged(settings.junk, body))
    return ThresholdPreview(**counts)


@router.put("/thresholds", response_model=ThresholdPreview)
def save_thresholds(
    body: ThresholdsModel,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
    counts_cache: CountsCache = Depends(get_counts_cache),
) -> ThresholdPreview:
    with factory() as session:
        settings_store.set_junk_thresholds(session, body.model_dump())
        thr = settings_store.effective_junk(session, settings)
        cult = curated_lists.cult_ids(session)
    junk.compute_and_store(factory, thr, cult_ids=cult)  # re-score with the new thresholds
    counts_cache.invalidate()  # new thresholds change what counts as flagged
    return ThresholdPreview(**junk.preview(factory, thr))


@router.post("/test/{service}", response_model=ServiceHealth)
async def test_connection(
    service: str,
    settings: Settings = Depends(get_settings),
    health_cache: HealthCache = Depends(get_health_cache),
) -> ServiceHealth:
    try:
        s = await check_service(settings, service)  # always a live probe, never the cache
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # The user just learned this service's real state — drop the cached sweep so
    # the health dots agree on the next poll.
    health_cache.invalidate()
    return ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
