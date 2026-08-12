"""Storage endpoints: where the disk went, and what it would cost to get it back.

Read-only. Nothing here proposes or executes anything — findings become actions
only through the existing engine, which is still the single chokepoint for every
mutation.

The baselines endpoint exists to be checked. These verdicts rest on the claim that
the library's own median describes it well, and that claim is worth being able to
inspect directly rather than taking on trust from whatever the outlier list says.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import outliers as outlier_analysis
from .deps import AuthDep, get_session_factory
from .schemas import (
    BaselinesResponse,
    BucketOut,
    MovieSizeResponse,
    SizeFindingOut,
)

router = APIRouter(prefix="/api/storage", tags=["storage"], dependencies=[AuthDep])


@router.get("/movies", response_model=MovieSizeResponse)
def movie_sizes(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> MovieSizeResponse:
    """Films whose file size does not match the film, biggest reclaim first."""
    with factory() as session:
        report = outlier_analysis.find(session, limit=max(1, min(limit, 1000)))
    return MovieSizeResponse(
        items=[
            SizeFindingOut(
                tmdb_id=f.tmdb_id,
                title=f.title,
                year=f.year,
                kind=f.kind,
                path=f.path,
                size=f.size,
                duration_ms=f.duration_ms,
                runtime_minutes=f.runtime_minutes,
                resolution=f.resolution,
                video_codec=f.video_codec,
                bytes_reclaimable=f.bytes_reclaimable,
                risk_tier=f.risk_tier,
                reasons=list(f.reasons),
            )
            for f in report.findings
        ],
        total_reclaimable=report.total_reclaimable,
        oversized_count=report.oversized_count,
        truncated_count=report.truncated_count,
        bad_rip_count=report.bad_rip_count,
        short_films_cleared=report.short_films_cleared,
    )


@router.get("/baselines", response_model=BaselinesResponse)
def baselines(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> BaselinesResponse:
    """What this library treats as an ordinary bitrate, per resolution and codec."""
    with factory() as session:
        measured = outlier_analysis.load_baselines(session)
    return BaselinesResponse(
        buckets=[
            BucketOut(
                resolution=b.resolution,
                codec=b.codec,
                samples=b.samples,
                median_rate=b.median_rate,
                observed=b.observed,
            )
            for b in measured.buckets
        ]
    )
