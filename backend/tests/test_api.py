"""HTTP surface: status, movies, health, token gating, and the safe action flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sift.db.models import Movie
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    # Disable all sources so /api/health needs no network.
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_version(client):
    c, _ = client
    body = c.get("/api/version").json()
    assert body["name"] == "sift"


def test_status_counts(client):
    c, factory = client
    assert c.get("/api/status").json()["counts"]["movies"] == 0
    with factory() as session:
        # in_plex=True → counts as owned (Plex is the source of truth).
        session.add(Movie(tmdb_id=603, title="The Matrix", in_plex=True, monitored=True))
        # In Radarr's catalog but not in Plex → indexed but not owned.
        session.add(Movie(tmdb_id=604, title="Reloaded", monitored=True, has_file=True))
        session.commit()
    counts = c.get("/api/status").json()["counts"]
    assert counts["movies"] == 2 and counts["owned"] == 1 and counts["monitored"] == 2


def test_movies_list_and_filter(client):
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", is_kids=False, in_plex=True))
        session.add(Movie(tmdb_id=862, title="Toy Story", is_kids=True, in_plex=True))
        # In Radarr's catalog only (wanted) — not in the Plex library.
        session.add(Movie(tmdb_id=604, title="Reloaded", monitored=True, in_plex=False))
        session.commit()

    everything = c.get("/api/movies").json()
    assert everything["total"] == 3

    in_plex = c.get("/api/movies", params={"in_plex": True}).json()
    assert in_plex["total"] == 2  # the Plex library, not the Radarr wanted item

    kids = c.get("/api/movies", params={"is_kids": True}).json()
    assert kids["total"] == 1 and kids["items"][0]["tmdb_id"] == 862

    search = c.get("/api/movies", params={"q": "matrix"}).json()
    assert search["total"] == 1 and search["items"][0]["title"] == "The Matrix"


def test_movie_detail_404(client):
    c, _ = client
    assert c.get("/api/movies/999999").status_code == 404


def test_health_reports_all_services(client):
    c, _ = client
    services = {s["service"] for s in c.get("/api/health").json()["services"]}
    assert services == {"plex", "radarr", "tautulli", "tmdb"}


def test_token_gating(settings, factory):
    settings.server.api_token = SecretStr("tok")
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/status", headers={"X-Sift-Token": "tok"}).status_code == 200
        assert c.get("/api/status", headers={"Authorization": "Bearer tok"}).status_code == 200
        assert c.get("/api/status", headers={"X-Sift-Token": "wrong"}).status_code == 401


def test_delete_action_is_proposed_not_executed_over_http(client):
    c, _ = client
    resp = c.post(
        "/api/actions",
        json={"type": "delete", "movie_tmdb_id": 603, "payload": {"delete_files": True}},
    )
    assert resp.status_code == 201
    action = resp.json()
    assert action["status"] == "proposed"  # never executed from the HTTP surface

    approved = c.post(f"/api/actions/{action['id']}/approve").json()
    assert approved["status"] == "approved"

    activity = c.get("/api/activity").json()
    assert any(a["id"] == action["id"] for a in activity)
