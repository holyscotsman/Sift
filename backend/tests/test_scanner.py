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
    assert any(e.get("event") == "terminal" for e in hub.events if isinstance(e, dict))


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c


def test_start_scan_joins_a_recent_running_scan(client, factory):
    # Idempotent start: the wizard fires one silently, so a second POST must join
    # the in-flight scan instead of racing a duplicate.
    with factory() as session:
        run = ScanRun(status=ScanStatus.RUNNING, started_at=datetime.now(UTC))
        session.add(run)
        session.commit()
        running_id = run.id
    resp = client.post("/api/scan")
    assert resp.status_code == 202
    assert resp.json()["scan_run_id"] == running_id


def test_start_scan_retires_a_stale_running_row(client, factory):
    # A RUNNING row from a dead server must not wedge scanning forever.
    with factory() as session:
        run = ScanRun(
            status=ScanStatus.RUNNING, started_at=datetime.now(UTC) - timedelta(hours=2)
        )
        session.add(run)
        session.commit()
        stale_id = run.id
    resp = client.post("/api/scan")
    assert resp.status_code == 202
    assert resp.json()["scan_run_id"] != stale_id
    with factory() as session:
        assert session.get(ScanRun, stale_id).status == ScanStatus.INTERRUPTED
