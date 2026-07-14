"""Settings: connection status, editable scoring thresholds (with live preview)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from ..ai.registry import ai_configured
from ..analysis import junk
from ..config import JunkThresholds, Settings
from ..services import settings_store
from ..services.health import check_service, gather_health
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import (
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
) -> SettingsResponse:
    health = await gather_health(settings)
    with factory() as session:
        thr = settings_store.effective_junk(session, settings)
    return SettingsResponse(
        connections=[
            ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
            for s in health
        ],
        thresholds=_thresholds_out(thr),
        ai_configured=ai_configured(settings),
        actions_dry_run=settings.actions.dry_run,
    )


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
) -> ThresholdPreview:
    with factory() as session:
        settings_store.set_junk_thresholds(session, body.model_dump())
        thr = settings_store.effective_junk(session, settings)
    junk.compute_and_store(factory, thr)  # re-score with the new thresholds
    return ThresholdPreview(**junk.preview(factory, thr))


@router.post("/test/{service}", response_model=ServiceHealth)
async def test_connection(
    service: str, settings: Settings = Depends(get_settings)
) -> ServiceHealth:
    try:
        s = await check_service(settings, service)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ServiceHealth(service=s.service, ok=s.ok, detail=s.detail, latency_ms=s.latency_ms)
