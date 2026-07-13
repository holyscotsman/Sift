"""Junk computation + analysis endpoints (with the kids-guard exclusion)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import Collection, CollectionMember, Movie, Rating, RatingSource
from sift.main import create_app


def _seed_library(factory):
    with factory() as session:
        # Clear junk: low rating, many votes, in Plex.
        junk_film = Movie(tmdb_id=603, title="Junk Film", in_plex=True, is_kids=False)
        junk_film.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        # Great film: excluded from candidates.
        good = Movie(tmdb_id=604, title="Great Film", in_plex=True, is_kids=False)
        good.ratings.append(Rating(source=RatingSource.IMDB, value=8.5, votes=5000))
        # Kids junk: scored but guarded → never a removal candidate.
        kid = Movie(tmdb_id=862, title="Kids Junk", in_plex=True, is_kids=True)
        kid.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        # Radarr-only (not in Plex): not part of the library → not scored.
        wanted = Movie(tmdb_id=999, title="Wanted", in_plex=False, monitored=True)
        wanted.ratings.append(Rating(source=RatingSource.IMDB, value=2.0, votes=500))
        session.add_all([junk_film, good, kid, wanted])
        session.commit()


def test_candidates_exclude_good_kids_and_non_library(factory):
    _seed_library(factory)
    scored = junk.compute_and_store(factory, JunkThresholds())
    assert scored == 3  # only the three in-Plex movies

    with factory() as session:
        cands = junk.candidates(session, JunkThresholds())
        ids = {m.tmdb_id for m, _ in cands}
    assert ids == {603}  # junk only; good kept, kids guarded, wanted not in library


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_junk_endpoint(client):
    c, factory = client
    _seed_library(factory)
    junk.compute_and_store(factory, JunkThresholds())

    body = c.get("/api/junk").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["tmdb_id"] == 603 and item["band"] == "junk"
    assert item["rationale"] and len(item["signals"]) >= 1


def test_missing_collections_endpoint(client):
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", in_plex=True))
        coll = Collection(tmdb_collection_id=2344, name="Matrix", owned_count=1, total_count=2)
        session.add(coll)
        session.add_all(
            [
                CollectionMember(
                    collection_id=2344, tmdb_id=603, title="The Matrix", year=1999, owned=True
                ),
                CollectionMember(
                    collection_id=2344, tmdb_id=605, title="Revolutions", year=2003, owned=False
                ),
            ]
        )
        session.commit()

    body = c.get("/api/missing/collections").json()
    assert len(body["collections"]) == 1
    gap = body["collections"][0]
    assert gap["owned_count"] == 1 and gap["total_count"] == 2
    assert {m["tmdb_id"] for m in gap["members"]} == {603, 605}
