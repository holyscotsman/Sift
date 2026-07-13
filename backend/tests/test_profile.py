"""Taste profile aggregation + editable weights."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import Movie
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_profile_aggregates_and_weights(client):
    c, factory = client
    with factory() as session:
        session.add(
            Movie(tmdb_id=1, title="A", year=1999, in_plex=True, genres=["Action", "Sci-Fi"])
        )
        session.add(Movie(tmdb_id=2, title="B", year=1995, in_plex=True, genres=["Action"]))
        # Not in Plex → excluded from the taste profile.
        session.add(Movie(tmdb_id=3, title="C", year=2001, in_plex=False, genres=["Drama"]))
        session.commit()

    body = c.get("/api/profile").json()
    assert body["library_size"] == 2
    genres = {g["name"]: g["count"] for g in body["genres"]}
    assert genres["Action"] == 2 and genres["Sci-Fi"] == 1 and "Drama" not in genres
    assert {e["name"] for e in body["eras"]} == {"1990s"}
    assert body["weights"]["genre"] == 0.5

    updated = c.put("/api/profile/weights", json={
        "genre": 0.9, "director": 0.3, "cast": 0.5, "keywords": 0.5, "era": 0.5,
    }).json()
    assert updated["weights"]["genre"] == 0.9
    assert c.get("/api/profile").json()["weights"]["genre"] == 0.9  # persisted
