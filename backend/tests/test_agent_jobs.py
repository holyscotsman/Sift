"""Transcode jobs: approved in Sift, carried out by the host.

A transcode replaces a file with a lossier one, which is a delete spread over
time. These pin that it is gated exactly as a delete is, from both sides — the
engine refuses to execute one, and the agent surface refuses to hand one out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.actions.engine import ActionEngine, ApprovalRequiredError
from sift.api import routes_agent
from sift.db.models import Action, ActionStatus, ActionType, FileJob
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
        job = routes_agent.create_job(
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
    body = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert body["job"] is None


def test_an_approved_job_is_handed_out_once(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_job(factory, engine, approved=True)

    first = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert first["job"]["id"] == job_id
    assert first["job"]["source_path"] == "/movies/matrix.mkv"

    # Claimed, so a second agent must not get the same work.
    second = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert second["job"] is None


def test_a_staged_instance_hands_out_nothing(client, engine, factory):
    """NEGATIVE CONTROL: dry-run is the server's floor. Approving the idea while
    the instance is configured not to issue real writes must not reach the disk."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True, dry_run=True)
    body = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert body["job"] is None


# ------------------------------------------------------------------------ auth


def test_the_agent_surface_refuses_a_wrong_token(client, engine, factory):
    """NEGATIVE CONTROL: this token is the only thing between an anonymous caller
    and a list of paths on someone's file server."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True)
    wrong = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": "wrong"})
    assert wrong.status_code == 401
    assert c.post("/api/agent/claim").status_code == 401


def test_with_no_token_configured_the_surface_explains_itself(client):
    c, _ = client
    response = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": "anything"})
    assert response.status_code == 400
    assert "agent token" in response.json()["detail"].lower()


# ---------------------------------------------------------------------- results


def test_a_success_must_bring_its_numbers(client, engine, factory):
    """NEGATIVE CONTROL: an unverifiable success is exactly how a failed encode
    gets swapped in for the real file."""
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_job(factory, engine, approved=True)
    c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN})

    bad = c.post(
        f"/api/agent/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": True},
    )
    assert bad.status_code == 400


def test_a_reported_success_closes_the_action_as_executed(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    action_id, job_id = _queue_job(factory, engine, approved=True)
    c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN})

    ok = c.post(
        f"/api/agent/{job_id}/result",
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
    c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN})

    body = c.post(
        f"/api/agent/{job_id}/result",
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
    before = c.get("/api/agent/capability").json()
    assert before["agent_configured"] is False

    _configure_agent(factory)
    after = c.get("/api/agent/capability").json()
    assert after["agent_configured"] is True


def test_jobs_are_visible_to_the_owner(client, engine, factory):
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=True)
    jobs = c.get("/api/agent/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["target_codec"] == "h265"


def test_the_job_list_needs_a_session(client, engine, factory):
    """NEGATIVE CONTROL: the agent token opens the agent surface only. It must
    not be a way into the owner's endpoints."""
    from sift.services import auth

    c, _ = client
    _configure_agent(factory)
    with factory() as session:
        # Through the real API rather than a hand-built row. A merged dict skips
        # every invariant the module maintains — the password hash, the signing
        # secret, and the cache invalidation that tells the running app an account
        # now exists — and a gate test that closes the gate by a route production
        # never takes is testing the fixture, not the gate.
        auth.create_account(session, "owner", "hunter2hunter2")
    assert c.get("/api/agent/jobs").status_code == 401
    assert c.get("/api/agent/jobs", headers={"X-Sift-Agent-Token": TOKEN}).status_code == 401


def test_a_job_row_alone_grants_nothing(client, engine, factory):
    """NEGATIVE CONTROL for the whole design: creating a job is not approval."""
    c, _ = client
    _configure_agent(factory)
    _queue_job(factory, engine, approved=False)
    with factory() as session:
        assert session.query(FileJob).count() == 1
    claimed = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN})
    assert claimed.json()["job"] is None


def _queue_delete_job(factory, engine) -> tuple[int, int]:
    """An approved *delete* job — what the reclaim page actually produces."""
    action = engine.propose(
        ActionType.DELETE,
        movie_tmdb_id=603,
        payload={"via": "agent", "title": "The Matrix"},
        dry_run=False,
    )
    engine.approve(action.id)
    with factory() as session:
        job = routes_agent.create_job(
            session,
            action_id=action.id,
            kind="delete",
            source_path="/movies/matrix.dup.mkv",
            source_size=30 * GB,
            label="surplus copy",
        )
        return action.id, job.id


def test_a_successful_delete_is_recorded_as_a_success(client, engine, factory):
    """A delete that worked must not be filed as a failure.

    The success branch required an output size and duration before it would record
    anything as done. Only a transcode has those — a delete produces no new file —
    so every delete the agent completed fell through to the failure branch and was
    recorded as failed, with the action marked FAILED and an invented error
    attached. The reclaim feature's entire output is delete jobs, so this was every
    one of them.
    """
    c, _ = client
    _configure_agent(factory)
    action_id, job_id = _queue_delete_job(factory, engine)

    body = c.post(
        f"/api/agent/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": True, "output_path": "/movies/.sift-trash/matrix.dup.mkv"},
    ).json()

    assert body["status"] == "done", body
    with factory() as session:
        action = session.get(Action, action_id)
        assert action.status == ActionStatus.EXECUTED
        assert action.error is None


def test_a_failed_delete_is_still_recorded_as_a_failure(client, engine, factory):
    """NEGATIVE CONTROL. Accepting every report as success would pass the test
    above and make the audit log worthless."""
    c, _ = client
    _configure_agent(factory)
    action_id, job_id = _queue_delete_job(factory, engine)

    body = c.post(
        f"/api/agent/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": False, "error": "permission denied"},
    ).json()

    assert body["status"] == "failed"
    with factory() as session:
        action = session.get(Action, action_id)
        assert action.status == ActionStatus.FAILED
        assert "permission denied" in (action.error or "")


def test_a_transcode_still_has_to_bring_its_numbers(client, engine, factory):
    """NEGATIVE CONTROL for the other direction: relaxing the delete case must not
    relax the transcode case, where a silent truncation looks exactly like a
    success and swapping it in destroys the film."""
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_job(factory, engine, approved=True)
    response = c.post(
        f"/api/agent/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": True},
    )
    assert response.status_code == 400


def test_a_job_claimed_and_never_reported_returns_to_the_queue(client, engine, factory):
    """A claim used to be a one-way door.

    Nothing anywhere moved a job out of `claimed`, so an agent that did the work
    and then failed to report — a dropped connection, a restart, a sleeping
    machine — left the job claimed for ever and its action recorded as approved
    but never executed, for work that had in fact happened.
    """
    from datetime import timedelta

    from sift.db.models import utcnow

    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_delete_job(factory, engine)

    first = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert first["job"]["id"] == job_id
    assert c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()["job"] is None
    # The agent vanishes without reporting.
    with factory() as session:
        job = session.get(FileJob, job_id)
        job.claimed_at = utcnow() - timedelta(hours=routes_agent.STALE_CLAIM_HOURS + 1)
        session.commit()

    again = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert again["job"] is not None and again["job"]["id"] == job_id


def test_a_job_claimed_moments_ago_is_left_alone(client, engine, factory):
    """NEGATIVE CONTROL, and the one that stops this being dangerous. A window too
    short would hand the same job to a second agent while the first is still
    encoding it — so a fresh claim must never be reclaimable."""
    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_delete_job(factory, engine)

    claimed = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()
    assert claimed["job"]["id"] == job_id
    for _ in range(3):
        assert (
            c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()["job"] is None
        )


def test_a_finished_job_is_never_requeued(client, engine, factory):
    """NEGATIVE CONTROL. Only `claimed` is swept. A job that reported is done, and
    re-running a delete that already succeeded would be work nobody asked for."""
    from datetime import timedelta

    from sift.db.models import utcnow

    c, _ = client
    _configure_agent(factory)
    _action_id, job_id = _queue_delete_job(factory, engine)
    c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN})
    c.post(
        f"/api/agent/{job_id}/result",
        headers={"X-Sift-Agent-Token": TOKEN},
        json={"ok": True, "output_path": "/movies/.sift-trash/matrix.dup.mkv"},
    )
    with factory() as session:
        job = session.get(FileJob, job_id)
        assert job.status == "done"
        job.claimed_at = utcnow() - timedelta(hours=routes_agent.STALE_CLAIM_HOURS + 1)
        session.commit()

    assert c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": TOKEN}).json()["job"] is None
    with factory() as session:
        # Asserted on the row, not on whether it was handed out. The claim loop
        # already refuses an executed action, so a handout check passes even when
        # the sweep has wrongly dragged a finished job back to "queued".
        assert session.get(FileJob, job_id).status == "done"
