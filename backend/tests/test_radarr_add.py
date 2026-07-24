"""Radarr add-payload builder, options resolution, and the /api/actions/add flow."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sift.config import RadarrConfig
from sift.main import create_app
from sift.services import radarr_add


def test_build_add_payload_shape():
    p = radarr_add.build_add_payload(
        27205, "Inception", root_folder_path="/movies", quality_profile_id=4
    )
    assert p["tmdbId"] == 27205
    assert p["qualityProfileId"] == 4
    assert p["rootFolderPath"] == "/movies"
    assert p["monitored"] is True
    assert p["addOptions"] == {"searchForMovie": True}


async def test_resolve_add_options_from_radarr():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/rootfolder":
            return httpx.Response(200, json=[{"path": "/data/movies"}, {"path": "/other"}])
        if request.url.path == "/api/v3/qualityprofile":
            return httpx.Response(200, json=[{"id": 6, "name": "HD"}, {"id": 7, "name": "4K"}])
        return httpx.Response(404)

    config = RadarrConfig(base_url="http://radarr.test", api_key=None)
    root, profile = await radarr_add.resolve_add_options(
        config, transport=httpx.MockTransport(handler)
    )
    assert root == "/data/movies" and profile == 6


async def test_resolve_add_options_without_connection():
    assert await radarr_add.resolve_add_options(RadarrConfig(base_url=None)) == (None, None)


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c


def test_add_movie_endpoint_stages_in_dry_run(client):
    # Add is autonomous (no approval) but staged by default — nothing sent to Radarr.
    resp = client.post("/api/actions/add", json={"tmdb_id": 605, "title": "The Matrix Reloaded"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "add" and body["status"] == "executed"
    assert body["dry_run"] is True
    assert body["payload"]["result"]["sent"] is False
    # It shows up in the activity feed.
    assert any(a["type"] == "add" for a in client.get("/api/activity").json())


def test_live_add_with_unreachable_radarr_is_400_not_500(settings, factory, monkeypatch):
    # In live mode, a Radarr network fault while resolving add options is a graceful
    # 400 ("check the connection"), never an unhandled 500.
    settings.actions.dry_run = False
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False

    async def boom(*_args, **_kwargs):
        raise httpx.ConnectError("radarr down")

    monkeypatch.setattr(radarr_add, "resolve_add_options", boom)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        resp = c.post("/api/actions/add", json={"tmdb_id": 605, "title": "X"})
    assert resp.status_code == 400
    assert "Radarr" in resp.json()["detail"]


async def test_resolve_add_options_prefers_saved_defaults():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/rootfolder":
            return httpx.Response(200, json=[{"path": "/data/movies"}, {"path": "/4k"}])
        if request.url.path == "/api/v3/qualityprofile":
            return httpx.Response(200, json=[{"id": 6, "name": "HD"}, {"id": 7, "name": "4K"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # The owner's saved choices win while Radarr still reports them…
    config = RadarrConfig(
        base_url="http://radarr.test",
        default_root_folder="/4k",
        default_quality_profile_id=7,
    )
    assert await radarr_add.resolve_add_options(config, transport=transport) == ("/4k", 7)

    # …and stale saved values (folder gone, profile deleted) fall back to
    # first-of-each rather than failing the add (negative control).
    stale = RadarrConfig(
        base_url="http://radarr.test",
        default_root_folder="/removed",
        default_quality_profile_id=99,
    )
    assert await radarr_add.resolve_add_options(stale, transport=transport) == (
        "/data/movies",
        6,
    )


def test_request_falls_back_to_staged_radarr_add_without_overseerr(client):
    # No Overseerr configured + dry-run floor on → identical to the staged add path.
    resp = client.post("/api/actions/request", json={"tmdb_id": 605, "title": "Reloaded"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "add" and body["dry_run"] is True
    assert body["payload"]["result"]["sent"] is False


def test_request_routes_through_overseerr_when_configured(settings, factory, monkeypatch):
    from pydantic import SecretStr

    from sift.api import routes_actions

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.actions.dry_run = False  # live writes enabled by the operator
    settings.overseerr.base_url = "http://overseerr.test"
    settings.overseerr.api_key = SecretStr("k")

    calls: list[int] = []

    class FakeOverseerr:
        def __init__(self, config):
            pass

        async def request_movie(self, tmdb_id: int):
            calls.append(tmdb_id)
            return {"id": 42, "status": 1}

        async def aclose(self):
            return None

    monkeypatch.setattr(routes_actions, "OverseerrClient", FakeOverseerr)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        body = c.post("/api/actions/request", json={"tmdb_id": 27205, "title": "Inception"}).json()
    assert calls == [27205]  # the request went to Overseerr, not Radarr
    assert body["status"] == "executed" and body["dry_run"] is False
    assert body["payload"]["via"] == "overseerr"
    assert body["payload"]["request_id"] == 42


def test_request_stays_staged_under_dry_run_even_with_overseerr(settings, factory, monkeypatch):
    # The dry-run floor beats Overseerr: nothing may leave Sift while staging is on.
    from pydantic import SecretStr

    from sift.api import routes_actions

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.overseerr.base_url = "http://overseerr.test"
    settings.overseerr.api_key = SecretStr("k")

    def explode(*a, **k):
        raise AssertionError("Overseerr must not be contacted in dry-run")

    monkeypatch.setattr(routes_actions, "OverseerrClient", explode)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        body = c.post("/api/actions/request", json={"tmdb_id": 605, "title": "Reloaded"}).json()
    assert body["dry_run"] is True
    assert body["payload"]["result"]["sent"] is False


def test_request_already_made_in_overseerr_records_not_errors(settings, factory, monkeypatch):
    # Overseerr answers 409 when a title's already been requested. That's not a
    # failure the user can act on by retrying — it must be recorded as a request,
    # not bounced back as an error that just invites an endless "Retry" loop.
    from pydantic import SecretStr

    from sift.api import routes_actions
    from sift.clients.base import ClientHTTPError

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.actions.dry_run = False
    settings.overseerr.base_url = "http://overseerr.test"
    settings.overseerr.api_key = SecretStr("k")

    class FakeOverseerr:
        def __init__(self, config):
            pass

        async def request_movie(self, tmdb_id: int):
            raise ClientHTTPError("overseerr: HTTP 409", 409)

        async def aclose(self):
            return None

    monkeypatch.setattr(routes_actions, "OverseerrClient", FakeOverseerr)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        resp = c.post("/api/actions/request", json={"tmdb_id": 27205, "title": "Inception"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "executed"
    assert body["payload"]["via"] == "overseerr"
    assert body["payload"]["request_status"] == "already_requested"


def test_request_overseerr_auth_failure_is_a_clear_400(settings, factory, monkeypatch):
    # A rejected API key shouldn't read the same as a generic "couldn't reach" —
    # the fix (re-enter the key) is different from the fix for a network fault.
    from pydantic import SecretStr

    from sift.api import routes_actions
    from sift.clients.base import ClientAuthError

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.actions.dry_run = False
    settings.overseerr.base_url = "http://overseerr.test"
    settings.overseerr.api_key = SecretStr("bad-key")

    class FakeOverseerr:
        def __init__(self, config):
            pass

        async def request_movie(self, tmdb_id: int):
            raise ClientAuthError("overseerr: authentication failed (401)")

        async def aclose(self):
            return None

    monkeypatch.setattr(routes_actions, "OverseerrClient", FakeOverseerr)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        resp = c.post("/api/actions/request", json={"tmdb_id": 27205, "title": "Inception"})
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]
