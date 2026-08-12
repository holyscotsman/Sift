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

from ..analysis import ledger as ledger_analysis
from ..analysis import outliers as outlier_analysis
from .deps import AuthDep, get_session_factory
from .schemas import (
    BaselinesResponse,
    BucketOut,
    LedgerFindingOut,
    LedgerResponse,
    MovieSizeResponse,
    PlanRequest,
    PlanResponse,
    PlanStepOut,
    SizeFindingOut,
    TierSummary,
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


def _finding_out(finding: ledger_analysis.Finding) -> LedgerFindingOut:
    return LedgerFindingOut(
        kind=finding.kind,
        target_kind=finding.target_kind,
        target_id=finding.target_id,
        title=finding.title,
        detail=finding.detail,
        bytes_reclaimable=finding.bytes_reclaimable,
        risk_tier=finding.risk_tier,
        reversible=finding.reversible,
        reasons=list(finding.reasons),
    )


@router.get("/ledger", response_model=LedgerResponse)
def reclaim_ledger(
    limit: int = 500,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> LedgerResponse:
    """Every finding in one currency, safest first.

    Ordered by risk tier before size on purpose: sorted by size alone the list
    would routinely put an irreversible downgrade above a duplicate copy that
    costs nothing to remove.
    """
    with factory() as session:
        book = ledger_analysis.build(session, limit=max(1, min(limit, 2000)))
    return LedgerResponse(
        items=[_finding_out(f) for f in book.findings],
        total_reclaimable=book.total_reclaimable,
        tiers=[
            TierSummary(
                tier=tier,
                label=ledger_analysis.TIER_LABELS[tier],
                bytes_reclaimable=book.by_tier.get(tier, 0),
                count=book.counts_by_tier.get(tier, 0),
            )
            for tier in sorted(ledger_analysis.TIER_LABELS)
        ],
    )


@router.post("/plan", response_model=PlanResponse)
def reclaim_plan(
    body: PlanRequest,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> PlanResponse:
    """The cheapest way to free a given amount, in regret rather than effort.

    Read-only: this proposes nothing and changes nothing. Acting on a step still
    goes through the action engine, one approval at a time.
    """
    with factory() as session:
        book = ledger_analysis.build(session, limit=2000)
    result = ledger_analysis.plan(book, max(0, body.target_bytes))
    return PlanResponse(
        target_bytes=result.target_bytes,
        steps=[
            PlanStepOut(finding=_finding_out(s.finding), running_total=s.running_total)
            for s in result.steps
        ],
        reached=result.reached,
        total=result.total,
        highest_tier=result.highest_tier,
    )
