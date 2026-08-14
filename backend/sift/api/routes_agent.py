"""File jobs — approved here, carried out by the host.

Sift runs on a machine that has never seen the media and cannot reach it, so it
neither deletes nor re-encodes anything. It records an approved intention; an agent on the
box holding the files claims the job, runs the encode, verifies the result, and
reports back. Same philosophy as the restart and update endpoints: hand control
to the host rather than pretend to have it.

**The agent polls; Sift never calls out.** A hook would need the media host
reachable from wherever Sift runs, which behind NAT it is not — and the codebase
already documents that trap elsewhere, where "localhost" means the Sift server
rather than your machine. Polling also means no inbound port is opened for this.

**Nothing becomes claimable without an approval.** ``/claim`` only ever returns
jobs whose action is APPROVED, which is the same guard that governs deletes,
reached from the other side.

**Why a delete comes through here rather than through Sonarr.** Sonarr can
remove an episode file it imported. The surplus copies duplicate detection finds
are the ones it never imported — manual copies, failed imports, leftovers — so
its API has no handle on them. The path is the only thing that does.

**The re-grab guard is not optional.** Sonarr will re-upgrade a downgraded season
on its next search unless its quality profile is changed too, and without that
this feature is a treadmill fighting its own automation. Creating a downgrade job
therefore records the profile change alongside it, and refuses when Sonarr is not
connected to make it.
"""

from __future__ import annotations

import hmac
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Action, ActionStatus, FileJob, utcnow
from ..services import config_store
from .deps import AuthDep, get_session_factory
from .schemas import (
    AgentCapability,
    FileJobClaimOut,
    FileJobOut,
    FileJobResultIn,
)

log = logging.getLogger("sift.transcode")

# Owner-facing: listing and capability. Behind the normal session auth.
router = APIRouter(prefix="/api/agent", tags=["agent"], dependencies=[AuthDep])

# Agent-facing: claim and report. Authenticated by the shared agent token
# instead, because the agent is a daemon with no session.
agent_router = APIRouter(prefix="/api/agent", tags=["agent"])


def _agent_token(factory: sessionmaker[Session]) -> str | None:
    with factory() as session:
        return (config_store.get_config(session).get("transcode") or {}).get("agent_token")


def _require_agent(
    factory: sessionmaker[Session], presented: str | None
) -> None:
    expected = _agent_token(factory)
    if not expected:
        raise HTTPException(
            status_code=400,
            detail=(
                "No transcode agent token set. Generate one and paste it into "
                "Settings › Connections › Transcoding, then give the same value "
                "to the agent on your media box."
            ),
        )
    # Constant-time: this token is the only thing standing between an anonymous
    # caller and a list of file paths.
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="bad agent token")


def _job_out(job: FileJob) -> FileJobOut:
    return FileJobOut(
        id=job.id,
        kind=job.kind,
        label=job.label,
        action_id=job.action_id,
        status=job.status,
        source_path=job.source_path,
        source_size=job.source_size,
        source_duration_ms=job.source_duration_ms,
        target_resolution=job.target_resolution,
        target_codec=job.target_codec,
        expected_max_bytes=job.expected_max_bytes,
        error=job.error,
    )


@router.get("/capability", response_model=AgentCapability)
def capability(
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> AgentCapability:
    """Whether the host can actually honour a transcode.

    Reported rather than assumed, so the UI never offers a button that leads
    nowhere — the same reason ``can_update`` exists for the deploy hook.
    """
    from .deps import get_state

    state = get_state(request)
    return AgentCapability(
        agent_configured=bool(_agent_token(factory)),
        # Without Sonarr a downgrade cannot be written back, and Sonarr would
        # simply re-upgrade the season on its next search.
        sonarr_connected=bool(state.settings.sonarr.enabled and state.settings.sonarr.base_url),
    )


@router.get("/jobs", response_model=list[FileJobOut])
def list_jobs(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> list[FileJobOut]:
    with factory() as session:
        jobs = list(session.scalars(select(FileJob).order_by(FileJob.id.desc())))
        return [_job_out(j) for j in jobs]


# How long a job may sit claimed before it is assumed abandoned. The agent's own
# encode ceiling is twelve hours, so a day is comfortably past any real job and
# well short of leaving a stuck one to sit for ever.
STALE_CLAIM_HOURS = 24


def _requeue_abandoned(session: Session) -> int:
    """Return long-claimed jobs to the queue.

    A claim was previously a one-way door: nothing anywhere moved a job out of
    ``claimed``. So an agent that finished the work and then failed to report —
    a dropped connection, a restart, a machine going to sleep — left the job
    claimed for ever, and its action recorded as approved-but-never-executed for
    work that had actually happened.

    Re-queueing is safe for both kinds, which is why this can be automatic. A
    delete whose file is already gone reports success on the spot rather than
    erroring, so the second run is what finally records the truth. A transcode
    re-runs the encode and verifies it before swapping anything, so the worst case
    is wasted CPU rather than a wrong file.
    """
    cutoff = utcnow() - timedelta(hours=STALE_CLAIM_HOURS)
    stale = list(
        session.scalars(
            select(FileJob).where(
                FileJob.status == "claimed",
                FileJob.claimed_at.is_not(None),
                FileJob.claimed_at < cutoff,
            )
        )
    )
    for job in stale:
        log.warning(
            "job %s was claimed %s and never reported — returning it to the queue",
            job.id,
            job.claimed_at,
        )
        job.status = "queued"
        job.claimed_at = None
    if stale:
        session.commit()
    return len(stale)


@agent_router.post("/claim", response_model=FileJobClaimOut)
def claim(
    x_sift_agent_token: str | None = Header(default=None),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> FileJobClaimOut:
    """Hand the agent the next approved job, or nothing.

    The approval check is done here rather than trusted from job creation: a job
    row is only ever a record of intent, and the action is the authority on
    whether that intent was ever agreed to.
    """
    _require_agent(factory, x_sift_agent_token)
    with factory() as session:
        _requeue_abandoned(session)
        queued = session.scalars(
            select(FileJob).where(FileJob.status == "queued").order_by(FileJob.id)
        )
        for job in queued:
            action = session.get(Action, job.action_id)
            if action is None or action.status != ActionStatus.APPROVED:
                # Never claimable. Left queued rather than failed so approving it
                # later is all that is needed.
                continue
            if action.dry_run:
                # Staged, not live. The owner has approved the idea but the
                # instance is configured not to issue real writes.
                continue
            job.status = "claimed"
            job.claimed_at = utcnow()
            session.commit()
            session.refresh(job)
            log.info("transcode job %s claimed by the agent", job.id)
            return FileJobClaimOut(job=_job_out(job))
    return FileJobClaimOut(job=None)


@agent_router.post("/{job_id}/result", response_model=FileJobOut)
def report(
    job_id: int,
    body: FileJobResultIn,
    x_sift_agent_token: str | None = Header(default=None),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> FileJobOut:
    """Record what the agent actually did.

    Sift does not decide whether the encode was good — the agent has the file and
    checks it there, before any swap. What is enforced here is that a job cannot
    be reported as done without the numbers to show for it, so a silent failure
    cannot be recorded as a success.
    """
    _require_agent(factory, x_sift_agent_token)
    with factory() as session:
        job = session.get(FileJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no transcode job {job_id}")

        if body.ok:
            # Only a transcode produces a new file to describe. Requiring those
            # numbers of every job filed every completed *delete* as a failure —
            # and deletes are all the reclaim feature produces.
            if job.kind == "transcode" and (
                not body.output_size or not body.output_duration_ms
            ):
                raise HTTPException(
                    status_code=400,
                    detail="a successful transcode must report the output size and duration",
                )
            job.status = "done"
            job.result = {
                "output_size": body.output_size,
                "output_duration_ms": body.output_duration_ms,
                "output_path": body.output_path,
            }
        else:
            job.status = "failed"
            job.error = body.error or "the agent reported a failure"

        job.finished_at = utcnow()
        action = session.get(Action, job.action_id)
        if action is not None:
            # Audit-only, exactly as an Overseerr request is: the write happened
            # outside this process, so nothing is dispatched to a writer and the
            # delete guard is untouched.
            action.status = (
                ActionStatus.EXECUTED if job.status == "done" else ActionStatus.FAILED
            )
            action.executed_at = utcnow()
            if job.status == "failed":
                action.error = job.error
            payload = dict(action.payload or {})
            payload["result"] = {"via": "transcode-agent", **(job.result or {})}
            action.payload = payload
        session.commit()
        session.refresh(job)
        return _job_out(job)


def create_job(
    session: Session,
    *,
    action_id: int,
    kind: str = "transcode",
    source_path: str,
    source_size: int | None = None,
    source_duration_ms: int | None = None,
    target_resolution: str | None = None,
    target_codec: str | None = None,
    expected_max_bytes: int | None = None,
    label: str | None = None,
) -> FileJob:
    """Record an approved intention. Called from the action layer, not the wire."""
    job = FileJob(
        action_id=action_id,
        kind=kind,
        source_path=source_path,
        source_size=source_size,
        source_duration_ms=source_duration_ms,
        target_resolution=target_resolution,
        target_codec=target_codec,
        expected_max_bytes=expected_max_bytes,
        label=label,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


__all__ = ["router", "agent_router", "create_job"]
