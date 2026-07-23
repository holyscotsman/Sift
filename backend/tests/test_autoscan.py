"""Automatic rescans: due logic, the tick guard rails, and schedule persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sift.db.models import ScanRun, ScanStatus
from sift.main import create_app
from sift.services import autoscan, settings_store


def _seed_completed(factory, *, hours_ago: float) -> None:
    with factory() as session:
        session.add(
            ScanRun(
                status=ScanStatus.COMPLETED,
                finished_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            )
        )
        session.commit()


def test_is_due_logic(factory):
    now = datetime.now(UTC)
    with factory() as session:
        assert autoscan.is_due(session, 6, now) is True  # never scanned → due
    _seed_completed(factory, hours_ago=1)
    with factory() as session:
        assert autoscan.is_due(session, 6, now) is False  # fresh → not due
    _seed_completed(factory, hours_ago=7)
    # Latest completed is the anchor — but the 1h-ago one is newer (higher id came
    # second); seed order matters: the 7h row is the most recent id, so due.
    with factory() as session:
        assert autoscan.is_due(session, 6, now) is True


class _Hub:
    async def publish(self, scan_id, message):  # noqa: ANN001
        return None

    async def publish_progress(self, progress):  # noqa: ANN001
        return None


def _fake_app(settings, factory):
    sift = SimpleNamespace(session_factory=factory, settings=settings, hub=_Hub())
    return SimpleNamespace(
        state=SimpleNamespace(sift=sift, active_scans=set(), scan_tasks=set())
    )


@pytest.fixture
def scan_settings(settings):
    for name in ("radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.plex.enabled = True
    settings.plex.base_url = "http://plex.test"  # no token → client skipped, scan no-ops
    return settings


async def test_tick_starts_when_due_and_only_then(scan_settings, factory, monkeypatch):
    # The tick's scheduling logic is under test, not the pipeline — stub the launch
    # to complete the run instantly.
    app = _fake_app(scan_settings, factory)
    launched: list[int] = []

    def fake_launch(_app, scan_id, *, resume=False):  # noqa: ANN001
        launched.append(scan_id)
        with factory() as session:
            run = session.get(ScanRun, scan_id)
            run.status = ScanStatus.COMPLETED
            run.finished_at = datetime.now(UTC)
            session.commit()

    monkeypatch.setattr(autoscan, "launch_scan", fake_launch)
    with factory() as session:
        settings_store.set_scan_interval(session, 6)

    started = await autoscan.tick(app)
    assert started is not None and launched == [started]

    # Freshly completed → the next tick does nothing.
    assert await autoscan.tick(app) is None


async def test_tick_respects_off_running_and_unconfigured(scan_settings, factory):
    app = _fake_app(scan_settings, factory)

    # Interval off → never starts, even though a scan has never run.
    assert await autoscan.tick(app) is None

    with factory() as session:
        settings_store.set_scan_interval(session, 6)

    # A scan already running in-process → skip.
    app.state.active_scans = {123}
    assert await autoscan.tick(app) is None
    app.state.active_scans = set()

    # Plex unconfigured → nothing to scan.
    scan_settings.plex.base_url = None
    assert await autoscan.tick(app) is None


def test_interval_validation(factory):
    with factory() as session:
        assert settings_store.set_scan_interval(session, 12) == 12
        assert settings_store.get_scan_interval(session) == 12
        with pytest.raises(ValueError):
            settings_store.set_scan_interval(session, 5)


def test_schedule_endpoint_round_trip(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        assert client.get("/api/settings").json()["scan_interval_hours"] == 0
        ok = client.put("/api/settings/scan_schedule", json={"interval_hours": 24})
        assert ok.status_code == 200 and ok.json()["interval_hours"] == 24
        assert client.get("/api/settings").json()["scan_interval_hours"] == 24
        assert (
            client.put("/api/settings/scan_schedule", json={"interval_hours": 5}).status_code
            == 422
        )
