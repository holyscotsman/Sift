"""Duplicate detection — and the two bugs that made it impossible before."""

from __future__ import annotations

from sqlalchemy import select

from sift.analysis import duplicates
from sift.db.models import Movie, PlexCopy


def _plex_item(rating_key, tmdb_id, title, section="Movies"):
    return {
        "tmdb_id": tmdb_id,
        "title": title,
        "year": 1999,
        "plex_rating_key": rating_key,
        "library_section": section,
        "is_kids": False,
        "imdb_id": None,
    }


def test_several_copies_of_one_film_are_all_recorded(factory, settings):
    """The original defect: movies are keyed by tmdb_id, so three rips of one film
    collapsed into a single row and only the last rating key survived. You cannot
    report on what was never recorded."""
    from sift.ingest.pipeline import ScanPipeline

    pipe = ScanPipeline(factory, settings)
    pipe._persist_plex([
        _plex_item("1001", 603, "The Matrix"),
        _plex_item("1002", 603, "The Matrix", section="4K Movies"),
        _plex_item("1003", 603, "The Matrix"),
        _plex_item("2001", 862, "Toy Story"),
    ])
    with factory() as session:
        assert session.scalar(select(Movie.tmdb_id).where(Movie.tmdb_id == 603)) == 603
        keys = {c.rating_key for c in session.scalars(select(PlexCopy))}
        assert keys == {"1001", "1002", "1003", "2001"}

        groups, surplus = duplicates.find(session)
        assert [g.tmdb_id for g in groups] == [603]  # only the duplicated one
        assert groups[0].surplus == 2  # keep one, two could go
        assert surplus == 2


def test_a_single_copy_is_not_a_duplicate(factory, settings):
    """NEGATIVE CONTROL: one copy each must report nothing at all."""
    from sift.ingest.pipeline import ScanPipeline

    ScanPipeline(factory, settings)._persist_plex([
        _plex_item("1001", 603, "The Matrix"),
        _plex_item("2001", 862, "Toy Story"),
    ])
    with factory() as session:
        groups, surplus = duplicates.find(session)
    assert groups == [] and surplus == 0


def test_copies_removed_from_plex_stop_being_counted(factory, settings):
    """Tidy up a duplicate on disk and the next scan must forget it, or the list
    keeps recommending work already done."""
    from sift.ingest.pipeline import ScanPipeline

    pipe = ScanPipeline(factory, settings)
    pipe._persist_plex([
        _plex_item("1001", 603, "The Matrix"),
        _plex_item("1002", 603, "The Matrix"),
    ])
    with factory() as session:
        assert duplicates.find(session)[1] == 1
    # Second scan sees only one copy — the other was deleted from disk.
    pipe._persist_plex([_plex_item("1001", 603, "The Matrix")])
    with factory() as session:
        assert duplicates.find(session)[1] == 0
        assert {c.rating_key for c in session.scalars(select(PlexCopy))} == {"1001"}


def test_watch_history_lands_on_a_non_primary_copy(factory, settings):
    """The knock-on bug. Tautulli reports plays against whichever copy was watched;
    matching only the movie row's single rating key discarded them, so a watched
    film read as never-played — which used to count toward removal."""
    from sift.db.models import WatchHistory
    from sift.ingest.pipeline import ScanPipeline

    pipe = ScanPipeline(factory, settings)
    pipe._persist_plex([
        _plex_item("1001", 603, "The Matrix"),
        _plex_item("1002", 603, "The Matrix"),
    ])
    # Play the FIRST copy. _persist_plex overwrites the movie row per item, so
    # "1002" ends up the primary — 1001 is exactly what the old lookup discarded.
    pipe._persist_watch([
        {"plex_rating_key": "1001", "plex_user": "Dad", "plays": 4,
         "last_played_at": None, "completion_pct": 1.0, "is_kids_account": False},
    ])
    with factory() as session:
        row = session.scalars(select(WatchHistory)).first()
    assert row is not None and row.movie_id == 603 and row.plays == 4


def test_the_plex_phase_does_not_query_per_film(factory, settings):
    """Regression pin. Recording copies was first written with session.merge() per
    item, which issues its own SELECT and flushes pending work each time — about
    four statements per film. That is invisible on local SQLite and crippling on a
    hosted database, where every statement is a network round trip: a few thousand
    films became minutes of latency and the phase looked hung.

    The bound is deliberately generous (a constant handful, not a per-film budget)
    so it pins the *shape* — preloaded, not per-item — without being brittle.
    """
    from sqlalchemy import event

    from sift.ingest.pipeline import ScanPipeline

    items = [
        _plex_item(str(10_000 + i), i, f"Film {i}")
        for i in range(1, 201)
    ]
    pipe = ScanPipeline(factory, settings)
    pipe._persist_plex(items)  # first pass populates

    statements = {"n": 0}
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_a, **_kw):
        statements["n"] += 1

    try:
        pipe._persist_plex(items)  # the rescan — the case that runs every scan
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # 200 films: per-item work would be ~800 statements. A preloaded pass is a
    # handful regardless of library size.
    assert statements["n"] < 25, f"{statements['n']} statements for 200 films — per-item again?"
