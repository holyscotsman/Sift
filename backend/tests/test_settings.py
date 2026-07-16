"""Settings: effective thresholds, live preview, and persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import Movie, Rating, RatingSource
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _seed(factory):
    with factory() as session:
        m = Movie(tmdb_id=700, title="Mid Film", in_plex=True)
        m.ratings.append(Rating(source=RatingSource.IMDB, value=4.4, votes=1200))
        session.add(m)
        session.commit()
    junk.compute_and_store(factory, JunkThresholds())


def test_get_settings_shape(client):
    c, _ = client
    body = c.get("/api/settings").json()
    assert body["ai_configured"] is False
    assert body["thresholds"]["min_votes"] == 50
    assert {s["service"] for s in body["connections"]} >= {"plex", "radarr", "model"}


def test_threshold_preview_and_save(client):
    c, factory = client
    _seed(factory)

    # Mid Film scores ~67.9 → junk under the default 60 cutoff.
    base = c.get("/api/settings").json()["thresholds"]
    strict = {**base, "junk_cutoff": 90.0}
    prev = c.post("/api/settings/thresholds/preview", json=strict).json()
    assert prev["junk"] == 0 and prev["borderline"] == 1  # re-banded, not junk anymore

    # Persist the stricter cutoff and confirm /api/junk now excludes it.
    c.put("/api/settings/thresholds", json=strict)
    assert c.get("/api/settings").json()["thresholds"]["junk_cutoff"] == 90.0
