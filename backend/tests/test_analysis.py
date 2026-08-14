"""Junk computation + analysis endpoints (with the kids-guard exclusion)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.analysis import junk, upgrades
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


def test_keep_override_removes_a_candidate_permanently(factory):
    # The owner's Keep is a standing verdict: even a clear junk score stays hidden,
    # and unsetting it brings the candidate back (negative control).
    _seed_library(factory)
    junk.compute_and_store(factory, JunkThresholds())
    with factory() as session:
        session.get(Movie, 603).keep_override = True
        session.commit()
        assert junk.candidates(session, JunkThresholds()) == []
    # A rescan (recompute) must not resurrect it either.
    junk.compute_and_store(factory, JunkThresholds())
    with factory() as session:
        assert junk.candidates(session, JunkThresholds()) == []
        session.get(Movie, 603).keep_override = False
        session.commit()
        assert {m.tmdb_id for m, _ in junk.candidates(session, JunkThresholds())} == {603}


def test_keep_endpoint_round_trip(factory, settings):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    _seed_library(factory)
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        r = client.post("/api/movies/603/keep", json={"keep": True})
        assert r.status_code == 200 and r.json()["keep_override"] is True
        assert client.get("/api/movies/603").json()["keep_override"] is True
        r = client.post("/api/movies/603/keep", json={"keep": False})
        assert r.json()["keep_override"] is False
        assert client.post("/api/movies/999999/keep", json={"keep": True}).status_code == 404


def _seed_upgrades(factory):
    with factory() as session:
        session.add_all(
            [
                # In Plex, has a file below cutoff → an upgrade candidate.
                Movie(
                    tmdb_id=603, title="Below Cutoff", in_plex=True, has_file=True,
                    cutoff_unmet=True, quality="WEBDL-720p", file_size=3_000_000_000,
                ),
                # Kids item below cutoff → still a candidate (upgrade isn't a removal).
                Movie(
                    tmdb_id=862, title="Kids Below Cutoff", in_plex=True, is_kids=True,
                    has_file=True, cutoff_unmet=True, quality="SDTV", file_size=800_000_000,
                ),
                # NEGATIVE CONTROL: in Plex, meets cutoff → not a candidate.
                Movie(
                    tmdb_id=604, title="Meets Cutoff", in_plex=True, has_file=True,
                    cutoff_unmet=False, quality="Bluray-1080p",
                ),
                # NEGATIVE CONTROL: below cutoff in Radarr but NOT in Plex → not a candidate.
                Movie(
                    tmdb_id=999, title="Wanted Below Cutoff", in_plex=False, monitored=True,
                    has_file=True, cutoff_unmet=True,
                ),
            ]
        )
        session.commit()


def test_upgrade_candidates_filter_and_order(factory):
    _seed_upgrades(factory)
    with factory() as session:
        assert upgrades.count(session) == 2
        cands = upgrades.candidates(session)
    ids = [c.tmdb_id for c in cands]
    assert set(ids) == {603, 862}  # meets-cutoff and non-Plex excluded
    assert ids[0] == 603  # ordered by file size desc (biggest re-grab first)


def test_classification_overrides_rating(factory):
    with factory() as session:
        # Low rating but US theatrical → protected (kept off the removal queue).
        theatrical = Movie(tmdb_id=1, title="Theatrical Flop", in_plex=True, us_theatrical=True)
        theatrical.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        # Good rating but adult → force-removed regardless of score.
        adult = Movie(tmdb_id=2, title="Adult", in_plex=True, is_adult=True)
        adult.ratings.append(Rating(source=RatingSource.IMDB, value=8.0, votes=5000))
        # Low rating + independent → removed.
        indie = Movie(tmdb_id=3, title="Indie Flop", in_plex=True, is_independent=True)
        indie.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        # Low rating, no facts → neutral, decided by the score (junk) → candidate.
        plain = Movie(tmdb_id=4, title="Plain Flop", in_plex=True)
        plain.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        session.add_all([theatrical, adult, indie, plain])
        session.commit()

    junk.compute_and_store(factory, JunkThresholds())
    with factory() as session:
        ids = {m.tmdb_id for m, _ in junk.candidates(session, JunkThresholds())}
    # Adult + independent + plain are cut; the theatrical film is protected.
    assert ids == {2, 3, 4}


def test_cult_classic_is_protected(factory):
    with factory() as session:
        m = Movie(tmdb_id=1, title="Cult Flop", in_plex=True, is_independent=True)
        m.ratings.append(Rating(source=RatingSource.IMDB, value=2.5, votes=300))
        session.add(m)
        session.commit()
    # Without the cult flag it's a removal; marked cult, it's protected.
    junk.compute_and_store(factory, JunkThresholds())
    with factory() as session:
        assert {m.tmdb_id for m, _ in junk.candidates(session, JunkThresholds())} == {1}
    junk.compute_and_store(factory, JunkThresholds(), cult_ids=frozenset({1}))
    with factory() as session:
        assert junk.candidates(session, JunkThresholds()) == []


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_upgrades_endpoint_and_status_count(client):
    c, factory = client
    _seed_upgrades(factory)

    body = c.get("/api/upgrades").json()
    assert body["total"] == 2
    assert {i["tmdb_id"] for i in body["items"]} == {603, 862}

    # The same figure surfaces on the Dashboard status counts.
    assert c.get("/api/status").json()["counts"]["upgrades"] == 2

    # And the Library filter narrows to exactly the below-cutoff library titles.
    filtered = c.get("/api/movies", params={"in_plex": True, "cutoff_unmet": True}).json()
    assert {i["tmdb_id"] for i in filtered["items"]} == {603, 862}


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


def _collection(session, coll_id: int, *, members: list[tuple[int, str, int | None, bool]]):
    from sift.db.models import Collection, CollectionMember

    session.add(
        Collection(
            tmdb_collection_id=coll_id,
            name=f"Collection {coll_id}",
            owned_count=sum(1 for m in members if m[3]),
            total_count=len(members),
        )
    )
    for tmdb_id, title, year, owned in members:
        session.add(
            CollectionMember(
                collection_id=coll_id, tmdb_id=tmdb_id, title=title, year=year, owned=owned
            )
        )


def test_collection_members_come_back_oldest_first(factory):
    """Members were fetched per collection with an ORDER BY; they are now read in
    one query and sorted here. The order is part of the answer — a collection
    reads as a timeline — so grouping must not quietly lose it."""
    from sift.analysis.collections import collection_gaps

    with factory() as session:
        _collection(
            session,
            77,
            members=[
                (3, "Third", 2005, False),
                (1, "First", 1999, True),
                (4, "Undated", None, False),
                (2, "Second", 2002, True),
            ],
        )
        session.commit()

    with factory() as session:
        gaps = collection_gaps(session)

    assert [m["title"] for m in gaps[0]["members"]] == ["First", "Second", "Third", "Undated"]


def test_the_collections_page_does_not_query_per_collection(factory):
    """One round trip per collection is free on SQLite and the dominant cost
    against the hosted database — on every load of the page. Counted rather than
    timed, for exactly that reason."""
    from sqlalchemy import event

    from sift.analysis.collections import collection_gaps

    with factory() as session:
        for n in range(12):
            _collection(
                session,
                100 + n,
                members=[(n * 10 + 1, "Owned", 2000, True), (n * 10 + 2, "Missing", 2001, False)],
            )
        session.commit()

    engine = factory.kw["bind"]
    selects: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    try:
        with factory() as session:
            gaps = collection_gaps(session)
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(gaps) == 12, "the fixture must produce gaps to read"
    assert len(selects) <= 3, f"{len(selects)} reads for 12 collections"
