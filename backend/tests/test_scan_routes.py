"""Starting, resuming and reading scans over HTTP.

A scan writes the whole library snapshot. Two of them at once against one
database is the one thing this endpoint exists to prevent, and the guard had no
test — the frontend has a pin saying the *client* refuses to start a second, which
proves nothing about a second browser tab, a curl, or the wizard's silent
auto-start landing at the same moment as the dashboard button.

The other half is the orphan case. A RUNNING row whose task died with the process
would wedge scanning forever if it were treated as live, which on a host that
restarts on deploy is not a rare state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import ScanRun, ScanStatus
from sift.db.session import init_db, make_engine, make_session_factory
from sift.main import create_app
from sift.services import auth


@pytest.fixture
def client(tmp_path, settings, monkeypatch):
    """An app whose scans never actually run — this is about the bookkeeping."""
    launched: list[tuple[int, bool]] = []

    def fake_launch(app, scan_run_id, *, resume):  # noqa: ANN001
        launched.append((scan_run_id, resume))

    monkeypatch.setattr("sift.api.routes_scan.launch_scan", fake_launch)

    engine = make_engine(tmp_path / "scan.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        c.launched = launched  # type: ignore[attr-defined]
        c.factory = factory  # type: ignore[attr-defined]
        yield c


def _mark_live(client: TestClient, scan_id: int) -> None:
    """Pretend a scan task is running in this process, as the real one does."""
    client.app.state.active_scans = {scan_id}


def test_a_second_start_joins_the_first_instead_of_racing_it(client):
    """The wizard auto-starts a scan silently and the dashboard button is right
    there. Two scans writing one snapshot is not a thing anyone wants, and it is
    not something the client can be trusted to prevent — a second tab is enough."""
    first = client.post("/api/scan")
    assert first.status_code == 202, first.text
    scan_id = first.json()["scan_run_id"]
    _mark_live(client, scan_id)

    second = client.post("/api/scan")

    assert second.status_code == 202
    assert second.json() == {"scan_run_id": scan_id, "resume": True}
    # And nothing new was launched.
    assert client.launched == [(scan_id, False)]


def test_an_orphaned_running_row_does_not_wedge_scanning_forever(client):
    """A RUNNING row whose task died with the process. On a host that restarts on
    deploy this is ordinary, and treating it as live would mean scanning never
    starts again without someone editing the database."""
    first = client.post("/api/scan")
    orphan = first.json()["scan_run_id"]
    # Deliberately *not* marked live: the row says RUNNING, the process has no task.
    client.app.state.active_scans = set()

    second = client.post("/api/scan")

    assert second.status_code == 202
    assert second.json()["resume"] is False
    assert second.json()["scan_run_id"] != orphan
    with client.factory() as session:
        assert session.get(ScanRun, orphan).status is ScanStatus.INTERRUPTED


def test_resuming_while_another_scan_is_live_is_refused(client):
    """Not a join: a resume names a *specific* run, and running it beside a
    different live one is two scans, which is the thing being prevented."""
    first = client.post("/api/scan").json()["scan_run_id"]
    with client.factory() as session:
        other = ScanRun(status=ScanStatus.INTERRUPTED)
        session.add(other)
        session.commit()
        other_id = other.id
    _mark_live(client, first)

    resp = client.post(f"/api/scan?resume_id={other_id}")

    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]


def test_NEGATIVE_CONTROL_resuming_the_run_that_is_already_live_is_a_no_op(client):
    """Asking to resume the thing already running is not an error — it is what a
    reconnecting client does — but it must not launch it twice."""
    first = client.post("/api/scan").json()["scan_run_id"]
    _mark_live(client, first)

    resp = client.post(f"/api/scan?resume_id={first}")

    assert resp.status_code == 202
    assert resp.json() == {"scan_run_id": first, "resume": True}
    assert client.launched == [(first, False)]


def test_resuming_a_scan_that_never_existed_is_a_404(client):
    resp = client.post("/api/scan?resume_id=99999")
    assert resp.status_code == 404


def test_reading_an_unknown_scan_is_a_404_not_a_crash(client):
    assert client.get("/api/scan/99999").status_code == 404


def test_scan_rows_serialise_after_their_session_closes(client):
    """Both read handlers return an ORM row out of a closed session.

    They `expunge` first, and the honest note is that removing the expunge leaves
    this green — checked by mutation. The attributes are already loaded by then,
    so nothing lazy-loads against a dead session under the current settings. The
    call is defensive rather than load-bearing, and this test covers the property
    that matters (the response serialises) rather than claiming to guard a line it
    does not."""
    client.post("/api/scan")
    client.post("/api/scan")

    one = client.get("/api/scan?limit=5")
    assert one.status_code == 200, one.text
    body = one.json()
    assert len(body) >= 1
    assert {"id", "status"} <= set(body[0])

    single = client.get(f"/api/scan/{body[0]['id']}")
    assert single.status_code == 200
    assert single.json()["id"] == body[0]["id"]
