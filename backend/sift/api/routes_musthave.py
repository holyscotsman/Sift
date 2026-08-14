"""Must-Have catalog endpoints: run the engine, list suggestions, dismiss one.

Suggestions are advisory: the engine proposes and gates, the owner decides. A
dismissed title is remembered and never re-suggested.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..ai import musthave
from ..db.models import Movie, MustHaveSuggestion
from ..services.counts_cache import CountsCache
from .deps import AuthDep, get_counts_cache, get_session_factory, get_state
from .schemas import MustHaveListResponse, MustHaveOut, MustHaveRunResponse

router = APIRouter(prefix="/api/musthave", tags=["musthave"], dependencies=[AuthDep])


@router.post("/run", response_model=MustHaveRunResponse)
async def run(
    request: Request, limit: int = Query(default=20, ge=1, le=50)
) -> MustHaveRunResponse:
    state = get_state(request)
    result = await musthave.run_musthave(state.session_factory, state.settings, limit=limit)
    state.counts_cache.invalidate()  # new suggestions change the pending count
    return MustHaveRunResponse(
        added=result["added"], considered=result["considered"], provider=result["provider"]
    )


@router.get("", response_model=MustHaveListResponse)
def list_suggestions(
    status: str = Query(default="suggested", pattern="^(suggested|dismissed)$"),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> MustHaveListResponse:
    with factory() as session:
        # Anti-join: a title acquired since suggestion drops out, without pulling
        # the whole owned-id column into Python on every page view.
        now_owned = (
            select(Movie.tmdb_id)
            .where(Movie.in_plex.is_(True), Movie.tmdb_id == MustHaveSuggestion.tmdb_id)
            .exists()
        )
        rows = session.scalars(
            select(MustHaveSuggestion)
            .where(MustHaveSuggestion.status == status, ~now_owned)
            .order_by(MustHaveSuggestion.vote_count.desc().nulls_last())
        ).all()
        items = [MustHaveOut.model_validate(s) for s in rows]
    return MustHaveListResponse(items=items)


@router.post("/{suggestion_id}/dismiss", response_model=MustHaveOut)
def dismiss(
    suggestion_id: int,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    counts_cache: CountsCache = Depends(get_counts_cache),
) -> MustHaveOut:
    with factory() as session:
        row = session.get(MustHaveSuggestion, suggestion_id)
        if row is None:
            raise HTTPException(status_code=404, detail="suggestion not found")
        row.status = "dismissed"
        session.commit()
        counts_cache.invalidate()  # the pending count must drop on the next poll
        return MustHaveOut.model_validate(row)


@router.post("/{suggestion_id}/restore", response_model=MustHaveOut)
def restore(
    suggestion_id: int,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    counts_cache: CountsCache = Depends(get_counts_cache),
) -> MustHaveOut:
    """Un-dismiss: the title re-enters the same gated suggestion pool it came
    from — a mis-click is no longer forever."""
    with factory() as session:
        row = session.get(MustHaveSuggestion, suggestion_id)
        if row is None:
            raise HTTPException(status_code=404, detail="suggestion not found")
        row.status = "suggested"
        session.commit()
        counts_cache.invalidate()
        return MustHaveOut.model_validate(row)


@router.get("/canon/coverage")
def canon_coverage(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> dict[str, int]:
    """How much of the validated canon is on the server.

    ``owned`` counts only entries already resolved to a TMDB id, so it is a floor
    rather than an estimate: while resolution is still catching up the real figure
    is higher than this. ``unresolved`` ships alongside it for exactly that reason
    — a coverage number without it would read as complete when it is not.
    """
    from ..services import canon_entries

    with factory() as session:
        return canon_entries.coverage(session)


@router.get("/canon")
def canon_missing(
    tier: int | None = None,
    limit: int = 100,
    offset: int = 0,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> dict[str, object]:
    """Canon films not on the server, strongest claim to canon first.

    Only entries already resolved to a TMDB id can be compared with the library,
    so this list grows as resolution catches up. It is a floor, not an estimate —
    which is what the coverage endpoint's ``unresolved`` count is there to say.
    """
    from ..analysis import canon_missing as canon_missing_analysis
    from ..services import canon_entries

    with factory() as session:
        rows, total = canon_missing_analysis.missing(
            session, tier=tier, limit=limit, offset=offset
        )
        counts = canon_entries.coverage(session)
    return {
        "items": [
            {
                "tmdb_id": row.tmdb_id,
                "imdb_id": row.imdb_id,
                "title": row.title,
                "year": row.year,
                "tier": row.tier,
                "sources": row.sources,
                "spine": row.spine,
                "rating": row.rating,
                "votes": row.votes,
            }
            for row in rows
        ],
        "total": total,
        "coverage": counts,
    }
