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


def test_movies_starts_with_letter_jump(client):
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=1, title="Alien", in_plex=True))
        session.add(Movie(tmdb_id=2, title="Amadeus", in_plex=True))
        session.add(Movie(tmdb_id=3, title="Braveheart", in_plex=True))
        session.add(Movie(tmdb_id=4, title="300", in_plex=True))
        session.commit()

    a = c.get("/api/movies", params={"starts_with": "A"}).json()
    assert {m["title"] for m in a["items"]} == {"Alien", "Amadeus"}

    b = c.get("/api/movies", params={"starts_with": "b"}).json()  # case-insensitive
    assert b["total"] == 1 and b["items"][0]["title"] == "Braveheart"

    # "#" bucket = titles not starting with a letter (digits/symbols).
    hashed = c.get("/api/movies", params={"starts_with": "#"}).json()
    assert hashed["total"] == 1 and hashed["items"][0]["title"] == "300"


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
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", in_plex=True, radarr_id=5001))
        session.commit()
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


def test_security_headers_on_every_response(client):
    c, _ = client
    headers = c.get("/api/version").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "same-origin"
    # Negative control: CSP is deliberately deferred (inline-styled SPA) — pin its
    # absence so adding one later is a conscious decision, not middleware drift.
    assert "Content-Security-Policy" not in headers


def test_gzip_only_for_large_responses(client):
    c, factory = client
    with factory() as session:
        for i in range(60):
            title = f"A film with a longish title number {i}"
            session.add(Movie(tmdb_id=1000 + i, title=title, in_plex=True))
        session.commit()
    big = c.get("/api/movies", headers={"Accept-Encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"
    # Negative control: tiny payloads stay uncompressed (below minimum_size).
    small = c.get("/api/version", headers={"Accept-Encoding": "gzip"})
    assert small.headers.get("content-encoding") != "gzip"


def test_status_actionable_queue_counts(client):
    from sift.db.models import MustHaveSuggestion, Score

    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=1, title="Junky", in_plex=True))
        # Negative control: same score but the owner said Keep — never counted.
        session.add(Movie(tmdb_id=2, title="Kept junk", in_plex=True, keep_override=True))
        session.add(Movie(tmdb_id=3, title="Clean", in_plex=True))
        session.add(Score(movie_id=1, junk_score=99.0))
        session.add(Score(movie_id=2, junk_score=99.0))
        session.add(Score(movie_id=3, junk_score=0.0))
        session.add(MustHaveSuggestion(tmdb_id=500, title="Missing gem", status="suggested"))
        # Negative controls: dismissed, and suggested-but-meanwhile-owned.
        session.add(MustHaveSuggestion(tmdb_id=501, title="Dismissed", status="dismissed"))
        session.add(MustHaveSuggestion(tmdb_id=3, title="Clean", status="suggested"))
        session.commit()
    counts = c.get("/api/status").json()["counts"]
    assert counts["junk_flagged"] == 1
    assert counts["musthave_pending"] == 1


def test_queue_counts_cached_but_invalidated_on_writes(client):
    # The queue counts are cached (30 s TTL) so /api/status polls don't re-score
    # the library — but a keep-override or dismissal must show on the NEXT poll,
    # proving the write paths invalidate rather than waiting out the TTL.
    from sift.db.models import MustHaveSuggestion, Score

    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=1, title="Junky", in_plex=True))
        session.add(Score(movie_id=1, junk_score=99.0))
        session.add(MustHaveSuggestion(tmdb_id=500, title="Missing gem", status="suggested"))
        session.commit()
    counts = c.get("/api/status").json()["counts"]
    assert counts["junk_flagged"] == 1 and counts["musthave_pending"] == 1

    c.post("/api/movies/1/keep", json={"keep": True})
    assert c.get("/api/status").json()["counts"]["junk_flagged"] == 0

    suggestion_id = c.get("/api/musthave").json()["items"][0]["id"]
    c.post(f"/api/musthave/{suggestion_id}/dismiss")
    assert c.get("/api/status").json()["counts"]["musthave_pending"] == 0


def test_movie_list_reports_filtered_total_size(client):
    from sift.db.models import Movie

    client, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=1, title="A", in_plex=True, file_size=1_000))
        session.add(Movie(tmdb_id=2, title="B", in_plex=True, file_size=2_000))
        session.add(Movie(tmdb_id=3, title="C", in_plex=False, file_size=4_000))
        session.commit()
    body = client.get("/api/movies?in_plex=true").json()
    assert body["total_size"] == 3_000  # only the filtered set counts
    assert client.get("/api/movies").json()["total_size"] == 7_000

    # Infinite-scroll economy: aggregates are computed once, on page 1 — later
    # pages return the items with zeroed totals (the client keeps page 1's).
    page2 = client.get("/api/movies?page=2&page_size=2").json()
    assert len(page2["items"]) == 1
    assert page2["total"] == 0 and page2["total_size"] == 0


def test_health_sweep_is_cached_until_invalidated(client, monkeypatch):
    # /api/health is polled every 20 s; the sweep behind it runs at most once per
    # TTL. Saving connections rebuilds runtime state, which must invalidate.
    from sift.services import health as health_service

    c, _ = client
    calls = {"n": 0}
    real = health_service.gather_health

    async def counting(settings):
        calls["n"] += 1
        return await real(settings)

    monkeypatch.setattr(health_service, "gather_health", counting)
    c.get("/api/health")
    c.get("/api/health")
    assert calls["n"] == 1  # second poll served from the cache

    # Saving connections must drop the cache — the next poll probes live again.
    c.put("/api/config", json={"connections": {}})
    c.get("/api/health")
    assert calls["n"] == 2


def test_csv_export_matches_filters_and_requires_token(settings, factory):
    settings.server.api_token = SecretStr("tok")
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        with factory() as session:
            session.add(
                Movie(tmdb_id=1, title='Comma, "Quoted"', in_plex=True, file_size=2_000_000_000)
            )
            session.add(Movie(tmdb_id=2, title="Not In Plex", in_plex=False))
            session.commit()
        # Negative control: a download link without the token is refused.
        assert c.get("/api/movies.csv").status_code == 401
        r = c.get("/api/movies.csv", params={"in_plex": True, "token": "tok"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        lines = r.text.strip().splitlines()
        assert lines[0].startswith("title,year,")
        assert len(lines) == 2  # header + the single in-Plex row: filters respected
        assert '"Comma, ""Quoted"""' in lines[1]  # proper CSV escaping
        assert "2.00" in lines[1]  # bytes rendered as GB


def test_decisions_backup_export(settings, factory):
    from sift.db.models import MustHaveSuggestion

    settings.server.api_token = SecretStr("tok")
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        with factory() as session:
            session.add(Movie(tmdb_id=1, title="Protected Gem", in_plex=True, keep_override=True))
            session.add(Movie(tmdb_id=2, title="Ordinary", in_plex=True))
            session.add(MustHaveSuggestion(tmdb_id=500, title="Not For Me", status="dismissed"))
            session.add(MustHaveSuggestion(tmdb_id=501, title="Still Pending", status="suggested"))
            session.commit()
        # Negative control: no token → refused.
        assert c.get("/api/export/decisions.json").status_code == 401
        body = c.get("/api/export/decisions.json", params={"token": "tok"}).json()
        assert [k["tmdb_id"] for k in body["keep_overrides"]] == [1]
        assert [d["tmdb_id"] for d in body["dismissed_musthaves"]] == [500]
        assert "junk_cutoff" in body["thresholds"]
        assert body["sift_version"]
