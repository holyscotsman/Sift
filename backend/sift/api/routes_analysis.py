"""Analysis endpoints: junk removal candidates, collection gaps, and recommendations.

Scores are deterministic and computed during the scan; these routes read and shape
them. Recommendations are deterministic too — TMDB's discovery graph seeded by your
highest-rated owned titles (see ``analysis/recommend.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import collections as coll_analysis
from ..analysis import junk as junk_analysis
from ..analysis import recommend as recommend_analysis
from ..analysis import scoring
from ..analysis import upgrades as upgrade_analysis
from ..config import Settings
from ..services import curated_lists, settings_store
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import (
    CollectionGap,
    CollectionMemberOut,
    JunkCandidate,
    JunkResponse,
    ListMovie,
    MissingCollectionsResponse,
    MissingList,
    MissingListsResponse,
    RecommendationsResponse,
    RecommendedMovie,
    SignalOut,
    UpgradeCandidateOut,
    UpgradesResponse,
)

_LIST_LABELS = {
    "cult": "Cult classics",
    "imdb_top": "IMDb top-ranked",
    "criterion": "Criterion-caliber classics",
}

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
            # A forced-removal classification (adult / low independent / low
            # international) leads the rationale; otherwise the score rationale stands.
            classifier_reason = str(payload.get("verdict_reason") or "")
            if payload.get("verdict") == "remove":
                band = "junk"  # a forced removal reads as junk, not its numeric band
            score_rationale = scoring.rationale(signals, band)
            rationale = (
                f"{classifier_reason} {score_rationale}".strip()
                if classifier_reason
                else score_rationale
            )
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
                    rationale=rationale,
                    signals=[SignalOut(**s) for s in signals],
                    ai_note=payload.get("ai_note"),
                )
            )
    return JunkResponse(items=items, total=len(items))


@router.get("/upgrades", response_model=UpgradesResponse)
def upgrades(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> UpgradesResponse:
    with factory() as session:
        rows = upgrade_analysis.candidates(session, limit=limit)
        total = upgrade_analysis.count(session)
    return UpgradesResponse(
        items=[
            UpgradeCandidateOut(
                tmdb_id=c.tmdb_id,
                title=c.title,
                year=c.year,
                poster_url=c.poster_url,
                library_section=c.library_section,
                quality=c.quality,
                file_size=c.file_size,
                is_kids=c.is_kids,
            )
            for c in rows
        ],
        total=total,
    )


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


@router.get("/missing/lists", response_model=MissingListsResponse)
def missing_lists(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> MissingListsResponse:
    with factory() as session:
        grouped = curated_lists.missing_from_lists(session)
    lists = [
        MissingList(
            name=name,
            label=_LIST_LABELS.get(name, name.replace("_", " ").title()),
            items=[ListMovie(**m) for m in items],
        )
        for name, items in sorted(grouped.items())
    ]
    return MissingListsResponse(lists=lists)


@router.get("/missing/recommendations", response_model=RecommendationsResponse)
async def missing_recommendations(
    limit: int = 24,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> RecommendationsResponse:
    """Taste-based suggestions grounded in your highest-rated owned titles, via TMDB's
    discovery graph. Deterministic: TMDB picks the candidates, we rank and explain them."""
    result = await recommend_analysis.recommendations(factory, settings, limit=limit)
    return RecommendationsResponse(
        items=[RecommendedMovie(**item) for item in result["items"]],
        note=result["note"],
    )
