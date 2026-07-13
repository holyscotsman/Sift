"""Action proposal / approval endpoints + the activity feed.

Phase 0 exposes the *safe* half of the action lifecycle over HTTP: propose,
approve, reject, and the audit feed. The delete is never executed from this
surface — execution is wired in Phase 3, still behind the ``ActionEngine`` guard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..actions.engine import ActionEngine
from ..db.models import Action
from .deps import AuthDep, get_action_engine, get_session_factory
from .schemas import ActionOut, ProposeActionIn

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[AuthDep])


@router.post("/actions", response_model=ActionOut, status_code=201)
def propose_action(
    body: ProposeActionIn, engine: ActionEngine = Depends(get_action_engine)
) -> Action:
    return engine.propose(
        body.type,
        movie_tmdb_id=body.movie_tmdb_id,
        payload=body.payload,
        actor=body.actor,
        dry_run=body.dry_run,
    )


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
def approve_action(
    action_id: int, engine: ActionEngine = Depends(get_action_engine)
) -> Action:
    try:
        return engine.approve(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject_action(
    action_id: int, engine: ActionEngine = Depends(get_action_engine)
) -> Action:
    try:
        return engine.reject(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/activity", response_model=list[ActionOut])
def activity(
    limit: int = 50, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> list[Action]:
    with factory() as session:
        rows = list(session.scalars(select(Action).order_by(Action.id.desc()).limit(limit)))
        for row in rows:
            session.expunge(row)
        return rows
