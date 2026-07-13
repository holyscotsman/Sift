"""Analysis endpoints: junk removal candidates and collection gaps.

Scores are deterministic and computed during the scan; these routes read and shape
them. Recommendations arrive with the Phase-2 embeddings layer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import collections as coll_analysis
from ..analysis import junk as junk_analysis
from ..analysis import scoring
from ..config import Settings
from ..services import settings_store
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import (
    CollectionGap,
    CollectionMemberOut,
    JunkCandidate,
    JunkResponse,
    MissingCollectionsResponse,
    RecommendationsResponse,
    SignalOut,
)

router = APIRouter(prefix="/api", tags=["analysis"], dependencies=[AuthDep])


@router.get("/junk", response_model=JunkResponse)
def junk(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> JunkResponse:
    with factory() as session:
        thr = settings_store.effective_junk(session, settings)
        rows = junk_analysis.candidates(session, thr, limit=limit)
        items: list[JunkCandidate] = []
        for movie, score in rows:
            payload = score.signals or {}
            signals = list(payload.get("signals", []))
            band = payload.get("band") or scoring.band(score.junk_score, thr)
            items.append(
                JunkCandidate(
                    tmdb_id=movie.tmdb_id,
                    title=movie.title,
                    year=movie.year,
                    poster_url=movie.poster_url,
                    library_section=movie.library_section,
                    quality=movie.quality,
                    file_size=movie.file_size,
                    junk_score=score.junk_score,
                    band=band,
                    kids_guard=bool(payload.get("kids_guard")),
                    rationale=scoring.rationale(signals, band),
                    signals=[SignalOut(**s) for s in signals],
                )
            )
    return JunkResponse(items=items, total=len(items))


@router.get("/missing/collections", response_model=MissingCollectionsResponse)
def missing_collections(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> MissingCollectionsResponse:
    with factory() as session:
        gaps = coll_analysis.collection_gaps(session)
    return MissingCollectionsResponse(
        collections=[
            CollectionGap(
                collection_id=g["collection_id"],
                name=g["name"],
                owned_count=g["owned_count"],
                total_count=g["total_count"],
                members=[CollectionMemberOut(**m) for m in g["members"]],
            )
            for g in gaps
        ]
    )


@router.get("/missing/recommendations", response_model=RecommendationsResponse)
def missing_recommendations() -> RecommendationsResponse:
    # Taste-based recommendations need the Phase-2 embeddings/profile layer.
    return RecommendationsResponse(
        items=[],
        note="Taste-based recommendations arrive with the AI layer (next).",
    )
