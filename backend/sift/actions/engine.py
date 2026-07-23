"""The single chokepoint for every catalog mutation.

Autonomy tiers (game plan §11):

* ``add`` / ``monitor`` / ``unmonitor`` — reversible; may execute autonomously; audited.
* ``delete`` (Radarr ``deleteFiles=true``) — **irreversible; requires an explicit,
  recorded approval before it is ever issued.**

The delete guard lives here and only here, and is locked by
``tests/test_actions_safety.py``. Do not add a second execution path around it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Action, ActionActor, ActionStatus, ActionType, Movie
from ..services.audit import AuditTrail
from .radarr_writes import RadarrWriter, WriteResult

log = logging.getLogger("sift.actions")

# Actions that are reversible and therefore allowed to run without an approval.
AUTONOMOUS_TYPES = frozenset({ActionType.ADD, ActionType.MONITOR, ActionType.UNMONITOR})


class ApprovalRequiredError(Exception):
    """Raised when an irreversible action is executed without a recorded approval."""


class ActionEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        writer: RadarrWriter,
        *,
        audit: AuditTrail | None = None,
    ) -> None:
        self.factory = session_factory
        self.writer = writer
        self.audit = audit or AuditTrail()

    # ------------------------------------------------------------------- lifecycle

    def propose(
        self,
        action_type: ActionType,
        *,
        movie_tmdb_id: int | None,
        payload: dict[str, Any] | None = None,
        actor: ActionActor = ActionActor.AUTO,
        dry_run: bool = True,
    ) -> Action:
        with self.factory() as session:
            action = Action(
                type=action_type,
                movie_tmdb_id=movie_tmdb_id,
                status=ActionStatus.PROPOSED,
                payload=payload or {},
                dry_run=dry_run,
                actor=actor,
            )
            session.add(action)
            session.commit()
            session.refresh(action)
            self.audit.record(action, "proposed")
            session.expunge(action)
            return action

    def approve(self, action_id: int, *, actor: ActionActor = ActionActor.USER) -> Action:
        with self.factory() as session:
            action = self._require(session, action_id)
            if action.status not in (ActionStatus.PROPOSED, ActionStatus.APPROVED):
                raise ValueError(f"cannot approve action in status {action.status}")
            action.status = ActionStatus.APPROVED
            action.approved_at = datetime.now(UTC)
            action.actor = actor
            session.commit()
            session.refresh(action)
            self.audit.record(action, "approved")
            session.expunge(action)
            return action

    def reject(self, action_id: int) -> Action:
        with self.factory() as session:
            action = self._require(session, action_id)
            action.status = ActionStatus.REJECTED
            session.commit()
            session.refresh(action)
            self.audit.record(action, "rejected")
            session.expunge(action)
            return action

    # -------------------------------------------------------------------- execute

    async def execute(self, action_id: int) -> Action:
        # Read the action's state up front; the guard decision is made before any
        # writer call can possibly happen.
        with self.factory() as session:
            action = self._require(session, action_id)
            action_type = action.type
            status = action.status
            dry_run = action.dry_run
            movie_id = action.movie_tmdb_id
            payload = dict(action.payload or {})

        if status in (ActionStatus.EXECUTED, ActionStatus.REJECTED):
            raise ValueError(f"action {action_id} is already {status}")

        # --- GOLDEN SAFETY RULE -------------------------------------------------
        # An irreversible delete is refused unless it has been explicitly approved.
        # This check is intentionally *before* any RadarrWriter call.
        if action_type == ActionType.DELETE and status != ActionStatus.APPROVED:
            self._mark(action_id, ActionStatus.FAILED, error="approval required for delete")
            raise ApprovalRequiredError(
                f"action {action_id}: a file delete requires explicit approval"
            )
        if action_type not in AUTONOMOUS_TYPES and action_type != ActionType.DELETE:
            raise ValueError(f"unknown action type {action_type}")

        try:
            result = await self._dispatch(action_type, movie_id, payload, dry_run)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            self._mark(action_id, ActionStatus.FAILED, error=str(exc))
            raise

        executed = self._mark(
            action_id, ActionStatus.EXECUTED, payload={**payload, "result": _summarize(result)}
        )
        self.audit.record(executed, "executed")
        return executed

    async def _dispatch(
        self, action_type: ActionType, movie_id: int | None, payload: dict[str, Any], dry_run: bool
    ) -> WriteResult:
        if action_type == ActionType.ADD:
            return await self.writer.add_movie(payload, dry_run=dry_run)
        # Monitor/unmonitor/delete operate on Radarr's own movie id, NOT the tmdb id.
        # Resolve it from the snapshot so a live write hits the right movie.
        if action_type == ActionType.MONITOR:
            return await self.writer.set_monitored(self._radarr_id(movie_id), True, dry_run=dry_run)
        if action_type == ActionType.UNMONITOR:
            return await self.writer.set_monitored(
                self._radarr_id(movie_id), False, dry_run=dry_run
            )
        if action_type == ActionType.DELETE:
            delete_files = bool(payload.get("delete_files", True))
            return await self.writer.delete_movie(
                self._radarr_id(movie_id), delete_files=delete_files, dry_run=dry_run
            )
        raise ValueError(f"unknown action type {action_type}")  # pragma: no cover

    def _radarr_id(self, tmdb_id: int | None) -> int:
        if tmdb_id is None:
            raise ValueError("action requires a movie id")
        with self.factory() as session:
            movie = session.get(Movie, tmdb_id)
            if movie is None or movie.radarr_id is None:
                raise ValueError(
                    f"movie {tmdb_id} isn't managed by Radarr — Sift acts through Radarr, "
                    "so it can't monitor or remove a title Radarr doesn't have"
                )
            return movie.radarr_id

    # --------------------------------------------------------------------- helpers

    def mark_executed_external(self, action_id: int) -> Action:
        """Record an action whose write already happened OUTSIDE the engine (e.g.
        an Overseerr request). Audit-only — nothing is dispatched; the golden
        delete guard is untouched because this never routes to the writer."""
        return self._mark(action_id, ActionStatus.EXECUTED)

    def _mark(
        self,
        action_id: int,
        status: ActionStatus,
        *,
        error: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Action:
        with self.factory() as session:
            action = self._require(session, action_id)
            action.status = status
            if error is not None:
                action.error = error
            if payload is not None:
                action.payload = payload
            if status == ActionStatus.EXECUTED:
                action.executed_at = datetime.now(UTC)
            session.commit()
            session.refresh(action)
            session.expunge(action)
            return action

    @staticmethod
    def _require(session: Session, action_id: int) -> Action:
        action = session.get(Action, action_id)
        if action is None:
            raise ValueError(f"action {action_id} not found")
        return action


def _summarize(result: WriteResult) -> dict[str, Any]:
    return {
        "method": result.method,
        "path": result.path,
        "dry_run": result.dry_run,
        "sent": result.sent,
        "response": result.response,
    }
