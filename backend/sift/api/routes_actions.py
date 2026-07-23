"""Action proposal / approval / execution endpoints + the activity feed.

The full action lifecycle is exposed here: propose, approve, reject, execute, and
the audit feed. Execution stays behind the ``ActionEngine`` golden guard — an
irreversible delete is refused (HTTP 403) unless it has been explicitly approved.

``dry_run`` is server-authoritative. The effective value is
``settings.actions.dry_run OR body.dry_run``: a client may opt *into* staging but
can never force a live write when the hosted instance is configured dry-run. Flip
``SIFT_ACTIONS__DRY_RUN=false`` to let approved actions actually reach Radarr.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..actions.engine import ActionEngine, ApprovalRequiredError
from ..clients.overseerr import OverseerrClient
from ..config import Settings
from ..db.models import Action, ActionActor, ActionType
from ..services import radarr_add
from .deps import AuthDep, get_action_engine, get_session_factory, get_settings
from .schemas import ActionOut, AddMovieIn, ProposeActionIn

router = APIRouter(prefix="/api", tags=["actions"], dependencies=[AuthDep])


@router.post("/actions", response_model=ActionOut, status_code=201)
def propose_action(
    body: ProposeActionIn,
    engine: ActionEngine = Depends(get_action_engine),
    settings: Settings = Depends(get_settings),
) -> Action:
    # The server's dry_run is a floor: a client can ask for staging but never for a
    # live write the operator hasn't enabled.
    dry_run = settings.actions.dry_run or body.dry_run
    return engine.propose(
        body.type,
        movie_tmdb_id=body.movie_tmdb_id,
        payload=body.payload,
        actor=body.actor,
        dry_run=dry_run,
    )


@router.post("/actions/request", response_model=ActionOut)
async def request_movie(
    body: AddMovieIn,
    engine: ActionEngine = Depends(get_action_engine),
    settings: Settings = Depends(get_settings),
) -> Action:
    """Request a missing movie. Overseerr is the preferred front door when it's
    configured (the request flows through Overseerr's own approval pipeline);
    otherwise this falls back to a direct Radarr add. The server dry-run floor
    applies to both paths — staged means nothing left Sift."""
    if settings.actions.dry_run or not (
        settings.overseerr.enabled and settings.overseerr.base_url and settings.overseerr.api_key
    ):
        # No Overseerr (or staging floor on) → the existing Radarr add path,
        # which itself honors dry-run.
        return await add_movie(body, engine, settings)

    client = OverseerrClient(settings.overseerr)
    try:
        result = await client.request_movie(body.tmdb_id)
    except Exception as exc:  # noqa: BLE001 - Overseerr down → honest 400, no silent fallback
        raise HTTPException(
            status_code=400,
            detail="Couldn't reach Overseerr to file the request — check the connection.",
        ) from exc
    finally:
        await client.aclose()
    # Audit trail: the request is recorded like any other action, tagged with its
    # route so Activity shows *where* it went.
    action = engine.propose(
        ActionType.ADD,
        movie_tmdb_id=body.tmdb_id,
        payload={
            "via": "overseerr",
            "title": body.title,
            "request_id": result.get("id"),
            "request_status": result.get("status"),
        },
        actor=ActionActor.USER,
        dry_run=False,
    )
    return engine.mark_executed_external(action.id)


@router.post("/actions/add", response_model=ActionOut)
async def add_movie(
    body: AddMovieIn,
    engine: ActionEngine = Depends(get_action_engine),
    settings: Settings = Depends(get_settings),
) -> Action:
    """Add a movie to Radarr. Autonomous (no approval needed), but staged unless
    SIFT_ACTIONS__DRY_RUN=false. Quality profile + root folder are resolved from Radarr
    for a live add."""
    dry_run = settings.actions.dry_run
    payload: dict[str, Any] = {"tmdbId": body.tmdb_id, "title": body.title}
    if not dry_run:
        try:
            root, profile = await radarr_add.resolve_add_options(settings.radarr)
        except Exception as exc:  # noqa: BLE001 - a network/HTTP fault is a 400, not a 500
            raise HTTPException(
                status_code=400,
                detail="Couldn't reach Radarr to resolve add options — check the connection.",
            ) from exc
        if root is None or profile is None:
            raise HTTPException(
                status_code=400,
                detail="Radarr root folder / quality profile unavailable — check the connection.",
            )
        payload = radarr_add.build_add_payload(
            body.tmdb_id, body.title, root_folder_path=root, quality_profile_id=profile
        )
    action = engine.propose(
        ActionType.ADD,
        movie_tmdb_id=body.tmdb_id,
        payload=payload,
        actor=ActionActor.USER,
        dry_run=dry_run,
    )
    return await engine.execute(action.id)


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


@router.post("/actions/{action_id}/execute", response_model=ActionOut)
async def execute_action(
    action_id: int, engine: ActionEngine = Depends(get_action_engine)
) -> Action:
    try:
        return await engine.execute(action_id)
    except ApprovalRequiredError as exc:
        # The golden guard: an unapproved delete is a policy refusal, not a crash.
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        # Unknown id or an illegal state transition (already executed/rejected).
        detail = str(exc)
        status = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/activity", response_model=list[ActionOut])
def activity(
    limit: int = Query(default=50, ge=1, le=1000),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> list[Action]:
    with factory() as session:
        rows = list(session.scalars(select(Action).order_by(Action.id.desc()).limit(limit)))
        for row in rows:
            session.expunge(row)
        return rows
