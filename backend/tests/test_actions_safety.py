"""The golden safety rule: a file delete is only ever issued after approval.

This test is load-bearing. It pins both directions:
  * an unapproved delete NEVER reaches the writer (the guard is before any send);
  * an approved delete does; and autonomous adds/monitors run without approval
    (proving the guard is specific to deletes, not a blanket block).
"""

from __future__ import annotations

import pytest

from sift.actions.engine import ActionEngine, ApprovalRequiredError
from sift.actions.radarr_writes import RadarrWriter, WriteResult
from sift.db.models import ActionStatus, ActionType


class SpyWriter(RadarrWriter):
    def __init__(self) -> None:
        super().__init__(None)
        self.calls: list[tuple] = []

    async def add_movie(self, payload, *, dry_run: bool = True) -> WriteResult:
        self.calls.append(("add", dry_run))
        return WriteResult("POST", "/api/v3/movie", payload, dry_run, sent=not dry_run)

    async def set_monitored(self, movie_id, monitored, *, dry_run: bool = True) -> WriteResult:
        self.calls.append(("monitor" if monitored else "unmonitor", movie_id, dry_run))
        return WriteResult("PUT", "/api/v3/movie/editor", {}, dry_run, sent=not dry_run)

    async def delete_movie(
        self, movie_id, *, delete_files: bool, dry_run: bool = True
    ) -> WriteResult:
        self.calls.append(("delete", movie_id, delete_files, dry_run))
        return WriteResult("DELETE", f"/api/v3/movie/{movie_id}", {}, dry_run, sent=not dry_run)

    @property
    def deletes(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "delete"]


@pytest.fixture
def engine(factory):
    return ActionEngine(factory, SpyWriter())


async def test_unapproved_delete_is_refused_and_never_issued(engine):
    action = engine.propose(
        ActionType.DELETE, movie_tmdb_id=603, payload={"delete_files": True}, dry_run=False
    )
    with pytest.raises(ApprovalRequiredError):
        await engine.execute(action.id)

    # The writer must NOT have been touched at all.
    assert engine.writer.deletes == []
    # And the action is recorded as failed, not executed.
    reloaded = engine.approve  # noqa: F841 - keep engine referenced
    with engine.factory() as session:
        from sift.db.models import Action

        assert session.get(Action, action.id).status == ActionStatus.FAILED


async def test_unapproved_delete_refused_even_in_dry_run(engine):
    # dry_run True would not touch files, but the guard is about *issuing* at all.
    action = engine.propose(ActionType.DELETE, movie_tmdb_id=1, payload={}, dry_run=True)
    with pytest.raises(ApprovalRequiredError):
        await engine.execute(action.id)
    assert engine.writer.deletes == []


async def test_approved_delete_executes_once(engine):
    action = engine.propose(
        ActionType.DELETE, movie_tmdb_id=603, payload={"delete_files": True}, dry_run=True
    )
    engine.approve(action.id)
    result = await engine.execute(action.id)

    assert result.status == ActionStatus.EXECUTED
    assert engine.writer.deletes == [("delete", 603, True, True)]


async def test_add_is_autonomous_without_approval(engine):
    # NEGATIVE CONTROL: the guard must be delete-specific. An add runs autonomously.
    action = engine.propose(ActionType.ADD, movie_tmdb_id=None, payload={"tmdbId": 27205})
    result = await engine.execute(action.id)
    assert result.status == ActionStatus.EXECUTED
    assert ("add", True) in engine.writer.calls


async def test_monitor_is_autonomous_without_approval(engine):
    action = engine.propose(ActionType.MONITOR, movie_tmdb_id=603)
    result = await engine.execute(action.id)
    assert result.status == ActionStatus.EXECUTED
    assert ("monitor", 603, True) in engine.writer.calls
