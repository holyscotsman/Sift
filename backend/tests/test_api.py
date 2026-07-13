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


def test_movie_detail_with_ratings_watch_and_score(client):
    from sift.analysis import junk
    from sift.config import JunkThresholds
    from sift.db.models import Rating, RatingSource, WatchHistory

    c, factory = client
    with factory() as session:
        m = Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True)
        m.ratings.append(Rating(source=RatingSource.IMDB, value=8.7, votes=1_900_000))
        m.watch_history.append(
            WatchHistory(movie_id=603, plex_user="Dad", plays=3, completion_pct=0.9)
        )
        session.add(m)
        session.commit()
    junk.compute_and_store(factory, JunkThresholds())

    body = c.get("/api/movies/603").json()
    assert body["title"] == "The Matrix"
    assert body["ratings"][0]["source"] == "imdb" and body["ratings"][0]["value"] == 8.7
    assert body["watch_history"][0]["plays"] == 3
    assert body["sift_score"] is not None and "band" in body["sift_score"]


def test_health_reports_all_services(client):
    c, _ = client
    services = {s["service"] for s in c.get("/api/health").json()["services"]}
    assert services == {"plex", "radarr", "tautulli", "tmdb", "model"}


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


def test_execute_unapproved_delete_is_forbidden(client):
    # The golden guard, surfaced over HTTP: an unapproved delete → 403, never issued.
    c, _ = client
    action = c.post(
        "/api/actions",
        json={"type": "delete", "movie_tmdb_id": 603, "payload": {"delete_files": True}},
    ).json()
    resp = c.post(f"/api/actions/{action['id']}/execute")
    assert resp.status_code == 403
    # And the action is now recorded failed, not executed.
    assert c.get("/api/activity").json()[0]["status"] == "failed"


def test_execute_approved_delete_is_staged_in_dry_run(client):
    # Default (hosted) posture is dry-run: an approved delete "executes" but is staged
    # — status executed, nothing sent. This is the safe default.
    c, _ = client
    action = c.post(
        "/api/actions",
        json={
            "type": "delete",
            "movie_tmdb_id": 603,
            "payload": {"delete_files": True},
            "dry_run": False,  # client asks to go live...
        },
    ).json()
    # ...but the server floor keeps it staged because SIFT_ACTIONS__DRY_RUN defaults on.
    assert action["dry_run"] is True
    c.post(f"/api/actions/{action['id']}/approve")
    done = c.post(f"/api/actions/{action['id']}/execute").json()
    assert done["status"] == "executed"
    assert done["dry_run"] is True
    assert done["payload"]["result"]["sent"] is False


def test_settings_reports_dry_run(client):
    c, _ = client
    assert c.get("/api/settings").json()["actions_dry_run"] is True
