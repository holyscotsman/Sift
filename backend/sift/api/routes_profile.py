"""Taste profile: aggregated breakdown + editable emphasis weights."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import profile as profile_analysis
from .deps import AuthDep, get_session_factory
from .schemas import ProfileBucket, ProfileResponse, ProfileWeights

router = APIRouter(prefix="/api/profile", tags=["profile"], dependencies=[AuthDep])


def _build(data: dict[str, Any], weights: dict[str, float]) -> ProfileResponse:
    def buckets(key: str) -> list[ProfileBucket]:
        return [ProfileBucket(**b) for b in data[key]]

    return ProfileResponse(
        genres=buckets("genres"),
        keywords=buckets("keywords"),
        directors=buckets("directors"),
        actors=buckets("actors"),
        eras=buckets("eras"),
        library_size=data["library_size"],
        weights=ProfileWeights(**weights),
    )


@router.get("", response_model=ProfileResponse)
def get_profile(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ProfileResponse:
    with factory() as session:
        data = profile_analysis.compute(session)
        weights = profile_analysis.get_weights(session)
    return _build(data, weights)


@router.put("/weights", response_model=ProfileResponse)
def put_weights(
    weights: ProfileWeights,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ProfileResponse:
    with factory() as session:
        saved = profile_analysis.set_weights(session, weights.model_dump())
        data = profile_analysis.compute(session)
    return _build(data, saved)
