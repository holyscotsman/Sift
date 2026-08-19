"""Analysis endpoints: junk removal candidates, collection gaps, and recommendations.

Scores are deterministic and computed during the scan; these routes read and shape
them. Recommendations are deterministic too — TMDB's discovery graph seeded by your
highest-rated owned titles (see ``analysis/recommend.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from ..ai import musthave
from ..analysis import collections as coll_analysis
from ..analysis import duplicates as dup_analysis
from ..analysis import junk as junk_analysis
from ..analysis import recommend as recommend_analysis
from ..analysis import scoring
from ..analysis import upgrades as upgrade_analysis
from ..config import Settings
from ..services import canon, canon_entries, curated_lists, settings_store
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import (
    CanonMissingResponse,
    CanonMovieOut,
    CanonRefreshResponse,
    CollectionGap,
    CollectionMemberOut,
    DuplicateCopyOut,
    DuplicateGroupOut,
    DuplicatesResponse,
    JunkCandidate,
    JunkResponse,
    ListMovie,
    MissingCollectionsResponse,
    MissingList,
    MissingListsResponse,
    RecommendationsResponse,
    RecommendedMovie,
    ShadowDiffResponse,
    ShadowDiffRow,
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
                    imdb_id=movie.imdb_id,
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


@router.get("/junk/shadow-diff", response_model=ShadowDiffResponse)
def junk_shadow_diff(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> ShadowDiffResponse:
    """Where the shadow score would disagree with the live one.

    v2 computes on every scan and changes nothing. This is how it earns the right
    to change something: the owner reads the real disagreements on their real
    library, rather than trusting a fixture that was chosen to prove a point. The
    cutover is a separate, deliberate decision and is not made here.
    """
    with factory() as session:
        thr = settings_store.effective_junk(session, settings)
        rows, summary = junk_analysis.shadow_diff(session, thr, limit=limit)
    return ShadowDiffResponse(
        items=[ShadowDiffRow(**row) for row in rows],
        compared=summary["compared"],
        disagreements=summary["disagreements"],
        v2_stricter=summary["v2_stricter"],
        v2_gentler=summary["v2_gentler"],
        v2_abstained=summary["v2_abstained"],
    )


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


@router.get("/missing/canon", response_model=CanonMissingResponse)
def canon_missing(
    limit: int = 500,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> CanonMissingResponse:
    """Canon titles absent from the PLEX library and not already requested. Radarr
    is ignored on purpose — monitored-but-not-downloaded still reads as missing."""
    with factory() as session:
        rows, total, requested_total = canon.missing(session, limit=max(1, min(limit, 1000)))
        return CanonMissingResponse(
            items=[
                CanonMovieOut(
                    tmdb_id=r.tmdb_id,
                    title=r.title,
                    year=r.year,
                    vote_average=r.vote_average,
                    vote_count=r.vote_count,
                    sources=list(r.sources or []),
                )
                for r in rows
            ],
            total=total,
            requested_total=requested_total,
        )


@router.post("/missing/canon/refresh", response_model=CanonRefreshResponse)
async def canon_refresh(
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> CanonRefreshResponse:
    """Rebuild the canon: run the AI curator first (best-effort — its proposals
    still pass the deterministic gates before storage), then the TMDB sweeps and
    curated merges. The canon itself stays backend-only."""
    curator_added = 0
    try:
        result = await musthave.run_musthave(factory, settings, limit=20)
        curator_added = int(result.get("added", 0))
    except Exception:  # noqa: BLE001 - a dead AI provider must not block the sweep
        curator_added = 0
    stats = await canon.refresh(factory, settings)
    with factory() as session:
        _, missing_total, _ = canon.missing(session, limit=1)
    return CanonRefreshResponse(
        canon_written=stats.get("written", 0),
        curator_added=curator_added,
        missing_total=missing_total,
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
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings),
) -> RecommendationsResponse:
    """Films worth acquiring: the validated canon first, then the taste graph.

    Canon entries need no API call and no ratings, which is what makes the list
    dependable; the discovery graph extends it with titles the canon does not
    mention. Deterministic throughout — nothing here is an LLM's opinion.
    """
    capped = max(1, min(limit, recommend_analysis.STORED_LIMIT))
    with factory() as session:
        items, counts = recommend_analysis.stored(session, limit=capped)
        # Only asked when the list came up short. A canon-first list is thin for
        # one reason far more often than any other — the canon arrives keyed by
        # IMDb id and only resolved entries can be compared against a library
        # keyed by TMDB id — and from the shelf that is invisible. Saying it is
        # the difference between "this is broken" and "this is still filling in".
        unresolved = (
            canon_entries.coverage(session)["unresolved"] if counts["total"] < capped else 0
        )
    if items:
        total = counts["total"]
        shown = f"Showing {len(items)} of {total}. " if total > len(items) else ""
        pending = (
            f" {unresolved} canon titles have no TMDB id yet — they join the list as "
            "resolution catches up."
            if unresolved
            else ""
        )
        return RecommendationsResponse(
            items=[RecommendedMovie(**m) for m in items],
            note=(
                f"{shown}{counts['canon']} from the validated canon, "
                f"{counts['taste']} from your taste graph.{pending}"
            ),
        )
    # Nothing stored yet — an instance that has not rescanned since this became a
    # scan phase. Compute live this once rather than showing an empty shelf.
    result = await recommend_analysis.recommendations(factory, settings, limit=capped)
    return RecommendationsResponse(
        items=[RecommendedMovie(**item) for item in result["items"]],
        note=result["note"],
    )


@router.get("/duplicates", response_model=DuplicatesResponse)
def list_duplicates(
    limit: int = 200,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DuplicatesResponse:
    """Films held more than once in Plex, most-duplicated first.

    The safest space you can reclaim: every film survives, only the surplus copies
    go, so there is no curation judgement to get wrong.
    """
    with factory() as session:
        groups, total_surplus = dup_analysis.find(session, limit=max(1, min(limit, 1000)))
    return DuplicatesResponse(
        items=[
            DuplicateGroupOut(
                tmdb_id=g.tmdb_id,
                title=g.title,
                year=g.year,
                copies=[
                    DuplicateCopyOut(rating_key=c.rating_key, library_section=c.library_section)
                    for c in g.copies
                ],
                surplus=g.surplus,
            )
            for g in groups
        ],
        total_surplus=total_surplus,
    )
