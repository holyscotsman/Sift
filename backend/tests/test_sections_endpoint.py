"""The endpoint that decides what each Plex library *is*.

`ingest/sections.py` — the planner — has its own tests. This is the HTTP layer
around it, which had none, and which carries a claim the planner cannot make on
its own: that correcting a mapping "takes effect on the next scan".

That claim depends on the write being followed by a live settings rebuild. Stored
but not rebuilt looks identical from the response and stays wrong until the
process restarts — and what it stays wrong *about* is whether a Home Videos
library is read as films, which is the difference between family footage sitting
quietly on disk and family footage in the removal queue.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sift.config import PlexConfig
from sift.db.session import init_db, make_engine, make_session_factory
from sift.main import create_app
from sift.services import auth

SECTIONS = {
    "MediaContainer": {
        "Directory": [
            {"key": "1", "title": "Films", "type": "movie", "agent": "tv.plex.agents.movie"},
            {"key": "2", "title": "TV Shows", "type": "show", "agent": "tv.plex.agents.series"},
            {"key": "3", "title": "Home Videos", "type": "movie",
             "agent": "com.plexapp.agents.none"},
            {"key": "4", "title": "Music", "type": "artist", "agent": "tv.plex.agents.music"},
        ]
    }
}


@pytest.fixture
def client(tmp_path, settings):
    """A signed-in app whose Plex answers with the four libraries above."""
    engine = make_engine(tmp_path / "sections.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

    settings.plex = PlexConfig(
        enabled=True, base_url="http://plex.test:32400", token="t"
    )
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


def _transport(handler=None):
    def default(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SECTIONS)

    return httpx.MockTransport(handler or default)


def test_a_home_videos_library_is_left_alone_by_default(client, monkeypatch):
    """The trap the endpoint's docstring names. Plex calls a Home Videos library a
    *movie* library, so without this it is read as films — into the removal queue,
    the film counts, and the size baselines every verdict is measured against."""
    from sift.clients import plex as plex_module

    original = plex_module.PlexClient.__init__

    def patched(self, config, **kwargs):
        original(self, config, transport=_transport(), **kwargs)

    monkeypatch.setattr(plex_module.PlexClient, "__init__", patched)

    resp = client.get("/api/config/sections")
    assert resp.status_code == 200, resp.text
    by_title = {s["title"]: s for s in resp.json()["sections"]}

    assert by_title["Home Videos"]["kind"] == "ignore"
    assert by_title["Films"]["kind"] == "movie"
    assert by_title["TV Shows"]["kind"] == "show"
    # Music is not video at all.
    assert by_title["Music"]["kind"] == "ignore"


def test_correcting_a_mapping_reaches_the_live_settings(client, monkeypatch):
    """"Takes effect on the next scan" is a claim about the *rebuild*, not about
    the write. Stored-but-not-rebuilt reads identically from the response and
    stays wrong until the process restarts."""
    from sift.clients import plex as plex_module

    original = plex_module.PlexClient.__init__

    def patched(self, config, **kwargs):
        original(self, config, transport=_transport(), **kwargs)

    monkeypatch.setattr(plex_module.PlexClient, "__init__", patched)

    resp = client.put(
        "/api/config/sections", json={"section_kinds": {"Home Videos": "movie"}}
    )
    assert resp.status_code == 200, resp.text

    by_title = {s["title"]: s for s in resp.json()["sections"]}
    assert by_title["Home Videos"]["kind"] == "movie"
    assert by_title["Home Videos"]["overridden"] is True

    # The response could be built from the request body alone. What matters is
    # the settings object the *next scan* will read.
    live = client.app.state.sift.settings  # the object the next scan reads
    assert live.plex.section_kinds.get("Home Videos") == "movie"


def test_NEGATIVE_CONTROL_an_unconnected_plex_says_so_rather_than_failing(tmp_path, settings):
    """A missing connection is a status, not a 500. The setup wizard calls this
    before anything is configured.

    Its own app rather than the shared fixture: `create_app` captures the settings
    it is given, so mutating them afterwards leaves the app holding the old copy —
    which is how the first version of this test ended up asserting against a Plex
    it thought was still connected.
    """
    engine = make_engine(tmp_path / "unconnected.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

    settings.plex = PlexConfig(enabled=False)
    with TestClient(create_app(settings, session_factory=factory)) as c:
        resp = c.get("/api/config/sections", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["sections"] == []
    assert "isn't connected" in resp.json()["detail"]


def test_NEGATIVE_CONTROL_an_unreachable_plex_says_so_rather_than_failing(client, monkeypatch):
    """Same for a Plex that is configured and simply not answering — the common
    case when a laptop is away from home."""
    from sift.clients import plex as plex_module

    original = plex_module.PlexClient.__init__

    def patched(self, config, **kwargs):
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        original(self, config, transport=_transport(boom), **kwargs)

    monkeypatch.setattr(plex_module.PlexClient, "__init__", patched)

    resp = client.get("/api/config/sections")
    assert resp.status_code == 200
    assert resp.json()["sections"] == []
    assert "Couldn't reach Plex" in resp.json()["detail"]
