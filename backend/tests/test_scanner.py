"""Scanner glue: a scan with no configured sources completes cleanly (no-op)."""

from __future__ import annotations

from sift.db.models import ScanRun, ScanStatus
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
