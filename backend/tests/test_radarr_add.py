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
