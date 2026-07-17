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
from .deps import AuthDep, get_session_factory, get_state
from .schemas import MustHaveListResponse, MustHaveOut, MustHaveRunResponse

router = APIRouter(prefix="/api/musthave", tags=["musthave"], dependencies=[AuthDep])


@router.post("/run", response_model=MustHaveRunResponse)
async def run(
    request: Request, limit: int = Query(default=20, ge=1, le=50)
) -> MustHaveRunResponse:
    state = get_state(request)
    result = await musthave.run_musthave(state.session_factory, state.settings, limit=limit)
    return MustHaveRunResponse(
        added=result["added"], considered=result["considered"], provider=result["provider"]
    )


@router.get("", response_model=MustHaveListResponse)
def list_suggestions(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> MustHaveListResponse:
    with factory() as session:
        owned = {
            tid
            for (tid,) in session.execute(select(Movie.tmdb_id).where(Movie.in_plex.is_(True)))
        }
        rows = session.scalars(
            select(MustHaveSuggestion)
            .where(MustHaveSuggestion.status == "suggested")
            .order_by(MustHaveSuggestion.vote_count.desc().nulls_last())
        ).all()
        items = [
            MustHaveOut(
                id=s.id,
                tmdb_id=s.tmdb_id,
                title=s.title,
                year=s.year,
                reason=s.reason,
                source=s.source,
                vote_average=s.vote_average,
                vote_count=s.vote_count,
            )
            for s in rows
            if s.tmdb_id not in owned  # a title acquired since suggestion drops out
        ]
    return MustHaveListResponse(items=items)


@router.post("/{suggestion_id}/dismiss", response_model=MustHaveOut)
def dismiss(
    suggestion_id: int, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> MustHaveOut:
    with factory() as session:
        row = session.get(MustHaveSuggestion, suggestion_id)
        if row is None:
            raise HTTPException(status_code=404, detail="suggestion not found")
        row.status = "dismissed"
        session.commit()
        return MustHaveOut(
            id=row.id,
            tmdb_id=row.tmdb_id,
            title=row.title,
            year=row.year,
            reason=row.reason,
            source=row.source,
            vote_average=row.vote_average,
            vote_count=row.vote_count,
        )
