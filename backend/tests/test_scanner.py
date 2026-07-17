"""Scanner glue: a scan with no configured sources completes cleanly (no-op)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sift.db.models import ScanRun, ScanStatus
from sift.main import create_app
from sift.services.scanner import create_scan_run, run_scan


class DummyHub:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, scan_id: int, message: dict) -> None:
        self.events.append(message)

    async def publish_progress(self, progress) -> None:
        self.events.append(progress)


async def test_scan_with_no_sources_completes(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    hub = DummyHub()
    scan_id = create_scan_run(factory)

    await run_scan(settings, factory, hub, scan_id)

    with factory() as session:
        run = session.get(ScanRun, scan_id)
        assert run.status == ScanStatus.COMPLETED
        # The AI phase ran and skipped cleanly (no provider configured).
        assert run.checkpoints["ai"]["status"] == "done"
    assert any(e.get("event") == "terminal" for e in hub.events if isinstance(e, dict))


async def test_ai_phase_failure_never_fails_the_scan(settings, factory, monkeypatch):
    # The AI phase is advisory: a provider blowing up must leave the scan COMPLETED.
    from pydantic import SecretStr

    from sift.ai import review as ai_review

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.ai.anthropic_api_key = SecretStr("sk-x")  # ai_configured → True

    async def boom(*_a, **_kw):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(ai_review, "run_review", boom)
    hub = DummyHub()
    scan_id = create_scan_run(factory)
    await run_scan(settings, factory, hub, scan_id)
    with factory() as session:
        assert session.get(ScanRun, scan_id).status == ScanStatus.COMPLETED


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c


def test_start_scan_joins_a_live_running_scan(client, factory):
    # Idempotent start: the wizard fires one silently, so a second POST must join
    # the in-flight scan instead of racing a duplicate. Liveness is exact (the id
    # has a task in this process), not an age heuristic — a big library may
    # legitimately scan for hours.
    with factory() as session:
        run = ScanRun(status=ScanStatus.RUNNING, started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        running_id = run.id
    client.app.state.active_scans = {running_id}
    resp = client.post("/api/scan")
    assert resp.status_code == 202
    assert resp.json()["scan_run_id"] == running_id


def test_start_scan_retires_an_orphaned_running_row(client, factory):
    # A RUNNING row with no live task (server died mid-scan) must not wedge
    # scanning forever — regardless of how recent it looks.
    with factory() as session:
        recent = ScanRun(status=ScanStatus.RUNNING, started_at=datetime.now(UTC))
        old = ScanRun(
            status=ScanStatus.RUNNING, started_at=datetime.now(UTC) - timedelta(hours=2)
        )
        session.add_all([recent, old])
        session.commit()
        orphan_ids = {recent.id, old.id}
    resp = client.post("/api/scan")
    assert resp.status_code == 202
    assert resp.json()["scan_run_id"] not in orphan_ids
    with factory() as session:
        for oid in orphan_ids:
            assert session.get(ScanRun, oid).status == ScanStatus.INTERRUPTED


def test_resume_refused_while_another_scan_is_live(client, factory):
    with factory() as session:
        live = ScanRun(status=ScanStatus.RUNNING, started_at=datetime.now(UTC))
        other = ScanRun(status=ScanStatus.INTERRUPTED, started_at=datetime.now(UTC))
        session.add_all([live, other])
        session.commit()
        live_id, other_id = live.id, other.id
    client.app.state.active_scans = {live_id}
    assert client.post(f"/api/scan?resume_id={other_id}").status_code == 409
    # Resuming the live scan itself is a no-op join, not a second pipeline.
    resp = client.post(f"/api/scan?resume_id={live_id}")
    assert resp.status_code == 202 and resp.json()["scan_run_id"] == live_id
