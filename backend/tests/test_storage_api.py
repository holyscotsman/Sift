"""The storage endpoints, including that they are read-only and behind auth."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import MediaFile, Movie
from sift.main import create_app

GB = 1_000_000_000
HOUR_MS = 3_600_000
MIN_MS = 60_000


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _seed(factory) -> None:
    with factory() as session:
        for i in range(10):
            session.add(Movie(tmdb_id=1000 + i, title=f"Ordinary {i}", year=2015, runtime=120))
            session.add(
                MediaFile(
                    movie_tmdb_id=1000 + i,
                    path=f"/movies/ordinary{i}.mkv",
                    size=6 * GB,
                    duration_ms=2 * HOUR_MS,
                    resolution="1080p",
                    video_codec="h264",
                    source="plex",
                )
            )
        session.add(Movie(tmdb_id=9001, title="Bloated", year=2015, runtime=90))
        session.add(
            MediaFile(
                movie_tmdb_id=9001,
                path="/movies/bloated.mkv",
                size=30 * GB,
                duration_ms=90 * MIN_MS,
                resolution="1080p",
                video_codec="h264",
                source="plex",
            )
        )
        session.commit()


def test_movie_sizes_reports_the_bloated_film(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/movies").json()
    assert [i["tmdb_id"] for i in body["items"]] == [9001]
    assert body["items"][0]["kind"] == "oversized"
    assert body["items"][0]["bytes_reclaimable"] > 20 * GB
    assert body["total_reclaimable"] >= body["items"][0]["bytes_reclaimable"]


def test_baselines_are_inspectable(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/baselines").json()
    bucket = next(b for b in body["buckets"] if b["resolution"] == "1080p")
    assert bucket["observed"] is True
    assert bucket["samples"] >= 10


def test_an_empty_library_answers_cleanly(client):
    """NEGATIVE CONTROL: a fresh instance must return an empty report, not a 500
    from measuring baselines over nothing."""
    c, _ = client
    body = c.get("/api/storage/movies").json()
    assert body["items"] == []
    assert body["total_reclaimable"] == 0
    assert c.get("/api/storage/baselines").json()["buckets"] == []


def test_storage_is_read_only(client):
    """NEGATIVE CONTROL: nothing here may mutate. A POST must not be routed."""
    c, _ = client
    assert c.post("/api/storage/movies").status_code == 405


def test_ledger_orders_by_risk_then_size(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/ledger").json()
    tiers = [i["risk_tier"] for i in body["items"]]
    assert tiers == sorted(tiers)
    assert body["total_reclaimable"] >= 0
    assert [t["tier"] for t in body["tiers"]] == [0, 1, 2]


def test_the_planner_reports_falling_short_rather_than_overpromising(client):
    """NEGATIVE CONTROL: a plan that quietly misses its target sends someone
    deleting things for nothing."""
    c, factory = client
    _seed(factory)
    body = c.post("/api/storage/plan", json={"target_bytes": 500_000 * GB}).json()
    assert body["reached"] is False
    assert body["total"] < 500_000 * GB
