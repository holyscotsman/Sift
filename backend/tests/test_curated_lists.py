"""Curated lists: seed, resolve, cult membership, and the missing-from-lists view."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import CuratedListEntry, Movie
from sift.main import create_app
from sift.services import curated_lists


def test_seed_is_idempotent_and_resolves(factory):
    with factory() as session:
        added = curated_lists.seed_defaults(session)
        assert added > 0
        # Second seed adds nothing.
        assert curated_lists.seed_defaults(session) == 0
        pending = curated_lists.pending_resolution(session)
        assert len(pending) == added  # all start unresolved

        # Resolve the first entry to a fake id and confirm it sticks.
        entry_id = pending[0][0]
        curated_lists.apply_resolution(session, {entry_id: 999})
        assert session.get(CuratedListEntry, entry_id).tmdb_id == 999


def test_cult_ids_and_missing(factory):
    with factory() as session:
        session.add_all(
            [
                # Cult entry owned (in Plex) → not "missing", but still a cult id.
                CuratedListEntry(list_name="cult", title="Owned Cult", year=1999, tmdb_id=10),
                # Cult entry not owned → missing.
                CuratedListEntry(list_name="cult", title="Missing Cult", year=1998, tmdb_id=11),
                # IMDb-top entry not owned → missing.
                CuratedListEntry(list_name="imdb_top", title="Missing Top", year=1994, tmdb_id=20),
                # Unresolved entry (no tmdb_id) → ignored everywhere.
                CuratedListEntry(list_name="cult", title="Unresolved", year=2000, tmdb_id=None),
            ]
        )
        session.add(Movie(tmdb_id=10, title="Owned Cult", in_plex=True))
        session.commit()

        assert curated_lists.cult_ids(session) == frozenset({10, 11})
        missing = curated_lists.missing_from_lists(session)
    assert {m["tmdb_id"] for m in missing["cult"]} == {11}  # owned one excluded
    assert {m["tmdb_id"] for m in missing["imdb_top"]} == {20}


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_missing_lists_endpoint(client):
    c, factory = client
    with factory() as session:
        session.add(
            CuratedListEntry(list_name="cult", title="Missing Cult", year=1998, tmdb_id=11)
        )
        session.commit()
    body = c.get("/api/missing/lists").json()
    cult = next(x for x in body["lists"] if x["name"] == "cult")
    assert cult["label"] == "Cult classics"
    assert cult["items"][0]["tmdb_id"] == 11 and cult["items"][0]["review_status"] == "pending"
