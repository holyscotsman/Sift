"""Storage endpoints: where the disk went, and what it would cost to get it back.

Read-only. Nothing here proposes or executes anything — findings become actions
only through the existing engine, which is still the single chokepoint for every
mutation.

The baselines endpoint exists to be checked. These verdicts rest on the claim that
the library's own median describes it well, and that claim is worth being able to
inspect directly rather than taking on trust from whatever the outlier list says.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import ledger as ledger_analysis
from ..analysis import outliers as outlier_analysis
from ..analysis import tv_duplicates as tv_dup_analysis
from ..analysis import tv_size as tv_size_analysis
from ..db.models import ActionActor, ActionType, MediaFile
from . import routes_agent as agent_routes
from .deps import AuthDep, get_action_engine, get_session_factory, get_settings
from .schemas import (
    BaselinesResponse,
    BucketOut,
    DuplicateEpisodeOut,
    InconsistencyOut,
    LedgerFindingOut,
    LedgerResponse,
    MovieSizeResponse,
    PlanRequest,
    PlanResponse,
    PlanStepOut,
    ReclaimActIn,
    ReclaimActOut,
    SeasonSizeOut,
    ShowDuplicatesOut,
    SizeFindingOut,
    TierSummary,
    TvStorageResponse,
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


@router.get("/tv", response_model=TvStorageResponse)
def tv_storage(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> TvStorageResponse:
    """The three TV questions, side by side.

    Which shows hold duplicate episodes, which seasons weigh more than their
    peers, and which seasons disagree with themselves.

    Inconsistency is reported here rather than in the ledger on purpose: fixing
    a season with one SD episode among nineteen HD ones usually *costs* space,
    so folding it into a list of reclaimable bytes would misrepresent it.
    """
    capped = max(1, min(limit, 1000))
    with factory() as session:
        shows, duplicate_bytes = tv_dup_analysis.find(session, limit=capped)
        baselines = outlier_analysis.load_baselines(session)
        sized, excess = tv_size_analysis.seasons(session, baselines=baselines, limit=capped)
        odd = tv_size_analysis.inconsistencies(session, limit=capped)

    return TvStorageResponse(
        duplicates=[
            ShowDuplicatesOut(
                tvdb_id=show.tvdb_id,
                title=show.title,
                library_section=show.library_section,
                episodes=[
                    DuplicateEpisodeOut(
                        season_number=e.season_number,
                        episode_number=e.episode_number,
                        title=e.title,
                        copies=len(e.copies),
                        surplus=e.surplus,
                        bytes_reclaimable=e.reclaimable,
                    )
                    for e in show.episodes
                ],
                surplus=show.surplus,
                bytes_reclaimable=show.reclaimable,
                surplus_paths=[
                    path
                    for episode in show.episodes
                    for copy in episode.copies
                    if not copy.keep
                    for path in copy.paths
                ],
            )
            for show in shows
        ],
        duplicate_bytes=duplicate_bytes,
        seasons=[
            SeasonSizeOut(
                tvdb_id=s.tvdb_id,
                title=s.title,
                season_number=s.season_number,
                air_year=s.air_year,
                episode_count=s.episode_count,
                total_bytes=s.total_bytes,
                bytes_per_hour=s.bytes_per_hour,
                per_episode=s.per_episode,
                resolution=s.resolution,
                video_codec=s.video_codec,
                excess=s.excess,
                bloated=s.bloated,
            )
            for s in sized
        ],
        season_excess_bytes=excess,
        inconsistencies=[
            InconsistencyOut(
                tvdb_id=i.tvdb_id,
                title=i.title,
                season_number=i.season_number,
                common_resolution=i.common_resolution,
                odd_resolutions=dict(i.odd_resolutions),
                rate_outliers=i.rate_outliers,
                episodes_affected=i.episodes_affected,
                reasons=list(i.reasons),
            )
            for i in odd
        ],
    )


@router.post("/act", response_model=ReclaimActOut)
def act_on_finding(
    body: ReclaimActIn,
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ReclaimActOut:
    """Turn a finding into an approval-gated job the host can carry out.

    Nothing is deleted here, and nothing is deleted when this returns. This
    records one audited action and the jobs behind it; the files go only once you
    approve, and only when an agent on the media box claims the work. Sift has no
    access to your files and this endpoint does not change that.

    The paths come from the finding you were looking at rather than being
    recomputed, so what gets approved is exactly what was on screen. They are
    checked against ``media_files`` before anything is recorded — a path Sift has
    never seen is refused outright, which stops this being a way to have the agent
    delete arbitrary things.
    """
    engine = get_action_engine(request)
    settings = get_settings(request)
    if not body.paths:
        raise HTTPException(status_code=400, detail="nothing selected")

    with factory() as session:
        known = set(
            session.scalars(select(MediaFile.path).where(MediaFile.path.in_(body.paths)))
        )
    unknown = [p for p in body.paths if p not in known]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"{len(unknown)} of those files aren't in the library snapshot — rescan first",
        )

    # dry_run is the server's floor, exactly as it is for film deletes: a client
    # may ask for a live write and never force one.
    dry_run = settings.actions.dry_run
    action = engine.propose(
        ActionType.DELETE,
        movie_tmdb_id=int(body.target_id) if body.target_kind == "movie" else None,
        payload={
            "via": "agent",
            "target_kind": body.target_kind,
            "target_id": body.target_id,
            "paths": list(body.paths),
            "label": body.label,
        },
        actor=ActionActor.USER,
        dry_run=dry_run,
    )

    job_ids: list[int] = []
    with factory() as session:
        sizes = {
            path: size
            for path, size in session.execute(
                select(MediaFile.path, MediaFile.size).where(MediaFile.path.in_(body.paths))
            )
        }
        for path in body.paths:
            job = agent_routes.create_job(
                session,
                action_id=action.id,
                kind="delete",
                source_path=path,
                source_size=sizes.get(path),
                label=body.label,
            )
            job_ids.append(job.id)

    return ReclaimActOut(
        action_id=action.id,
        job_ids=job_ids,
        dry_run=dry_run,
        detail=(
            "Staged. Your approval is recorded and nothing will be removed while "
            "the server is in dry-run."
            if dry_run
            else "Approve it and the agent on your media box will remove these files."
        ),
    )
