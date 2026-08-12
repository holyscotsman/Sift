"""Transcode jobs: approved in Sift, carried out by the host.

A transcode replaces a file with a lossier one, which is a delete spread over
time. These pin that it is gated exactly as a delete is, from both sides — the
engine refuses to execute one, and the agent surface refuses to hand one out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.actions.engine import ActionEngine, ApprovalRequiredError
from sift.api import routes_transcode
from sift.db.models import ActionStatus, ActionType, TranscodeJob
from sift.main import create_app
from sift.services import config_store

GB = 1_000_000_000
TOKEN = "agent-secret-token"


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


@pytest.fixture
def engine(settings, factory):
    # The same spy the delete-safety tests use, so "the writer was never
    # touched" means the same thing in both files.
    from tests.test_actions_safety import SpyWriter

    return ActionEngine(factory, SpyWriter())


def _configure_agent(factory) -> None:
    with factory() as session:
        config_store.set_config(session, {"transcode": {"agent_token": TOKEN}})


def _queue_job(factory, engine, *, approved: bool, dry_run: bool = False) -> tuple[int, int]:
    action = engine.propose(
        ActionType.TRANSCODE,
        movie_tmdb_id=603,
        payload={"title": "The Matrix"},
        dry_run=dry_run,
    )
    if approved:
        engine.approve(action.id)
    with factory() as session:
        job = routes_transcode.create_job(
            session,
            action_id=action.id,
            source_path="/movies/matrix.mkv",
            source_size=30 * GB,
            source_duration_ms=136 * 60_000,
            target_resolution="1080p",
            target_codec="h265",
            expected_max_bytes=8 * GB,
        )
        return action.id, job.id


# ------------------------------------------------------------------- the gate


async def test_an_unapproved_transcode_is_refused_by_the_engine(engine):
    """The same guard that governs deletes, reached by the new action type."""
    action = engine.propose(ActionType.TRANSCODE, movie_tmdb_id=603, dry_run=False)
    with pytest.raises(ApprovalRequiredError):
        await engine.execute(action.id)


async def test_an_approved_transcode_is_still_not_executed_here(engine):
    """Sift has no access to the files and never will. Approving one makes it
    claimable by the host; it does not make Sift able to do it."""
    action = engine.propose(ActionType.TRANSCODE, movie_tmdb_id=603, dry_run=False)
    engine.approve(action.id)
    with pytest.raises(ValueError, match="carried out by the host"):
        await engine.execute(action.id)
    assert engine.writer.calls == []  # nothing was dispatched anywhere


def test_an_unapproved_job_is_never_handed_out(client, engine, factory):
    """NEGATIVE CONTROL, and the important one. A job row is a record of intent;
    the action is the authority on whether that intent was ever agreed to."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=False)
    body = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert body["job"] is None


def test_an_approved_job_is_handed_out_once(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_job(factory, engine, approved=True)

    first = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert first["job"]["id"] == job_id
    assert first["job"]["source_path"] == "/movies/matrix.mkv"

    # Claimed, so a second agent must not get the same work.
    second = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert second["job"] is None


def test_a_staged_instance_hands_out_nothing(client, engine, factory):
    """NEGATIVE CONTROL: dry-run is the server's floor. Approving the idea while
    the instance is configured not to issue real writes must not reach the disk."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True, dry_run=True)
    body = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert body["job"] is None


# ------------------------------------------------------------------------ auth


def test_the_agent_surface_refuses_a_wrong_token(client, engine, factory):
    """NEGATIVE CONTROL: this token is the only thing between an anonymous caller
    and a list of paths on someone's file server."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True)
    wrong = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": "wrong"})
    assert wrong.status_code == 401
    assert c.post("/api/transcode/claim").status_code == 401


def test_with_no_token_configured_the_surface_explains_itself(client):
    c, _ = client
    response = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": "anything"})
    assert response.status_code == 400
    assert "agent token" in response.json()["detail"].lower()


# ---------------------------------------------------------------------- results


def test_a_success_must_bring_its_numbers(client, engine, factory):
    """NEGATIVE CONTROL: an unverifiable success is exactly how a failed encode
    gets swapped in for the real file."""
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_job(factory, engine, approved=True)
    c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN})

    bad = c.post(
        f"/api/transcode/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": True},
    )
    assert bad.status_code == 400


def test_a_reported_success_closes_the_action_as_executed(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    action_id, job_id = _queue_job(factory, engine, approved=True)
    c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN})

    ok = c.post(
        f"/api/transcode/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={
            "ok": True,
            "output_path": "/movies/matrix.h265.mkv",
            "output_size": 7 * GB,
            "output_duration_ms": 136 * 60_000,
        },
    ).json()
    assert ok["status"] == "done"

    from sift.db.models import Action

    with factory() as session:
        action = session.get(Action, action_id)
        assert action is not None
        assert action.status == ActionStatus.EXECUTED
        assert action.payload["result"]["via"] == "transcode-agent"


def test_a_reported_failure_is_recorded_as_one(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    action_id, job_id = _queue_job(factory, engine, approved=True)
    c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN})

    body = c.post(
        f"/api/transcode/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": False, "error": "output was 4 seconds long"},
    ).json()
    assert body["status"] == "failed"

    from sift.db.models import Action

    with factory() as session:
        action = session.get(Action, action_id)
        assert action is not None
        assert action.status == ActionStatus.FAILED
        assert "4 seconds" in (action.error or "")


# ------------------------------------------------------------------ capability


def test_capability_is_reported_rather_than_assumed(client, factory):
    """The UI must never offer a button the host cannot honour — the same reason
    can_update exists for the deploy hook."""
    c, _ = client
    before = c.get("/api/transcode/capability").json()
    assert before["agent_configured"] is False

    _configure_agent(factory)
    after = c.get("/api/transcode/capability").json()
    assert after["agent_configured"] is True


def test_jobs_are_visible_to_the_owner(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True)
    jobs = c.get("/api/transcode/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["target_codec"] == "h265"


def test_the_job_list_needs_a_session(client, engine, factory):
    """NEGATIVE CONTROL: the agent token opens the agent surface only. It must
    not be a way into the owner's endpoints."""
    from sift.db.models import Setting

    c, _ = client
    _configure_agent(factory)
    with factory() as session:
        session.merge(Setting(key="auth", value={"username": "x", "password_hash": "y"}))
        session.commit()
    assert c.get("/api/transcode/jobs").status_code == 401
    assert c.get("/api/transcode/jobs", headers={"X-Sift-Agent-Token": TOKEN}).status_code == 401


def test_a_job_row_alone_grants_nothing(client, engine, factory):
    """NEGATIVE CONTROL for the whole design: creating a job is not approval."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=False)
    with factory() as session:
        assert session.query(TranscodeJob).count() == 1
    claimed = c.post("/api/transcode/claim", headers={"X-Sift-Agent-Token": TOKEN})
    assert claimed.json()["job"] is None
