"""What scoring a library costs the database, and that batching changed nothing else.

Scoring is the largest loop in a scan — every library title, every time. It used
to read four rows at a time: the film, its ratings, its watch history, and a
lazily loaded score row. Round trips are free on the file-backed SQLite these
tests run on and are the dominant cost against the hosted Postgres this ships to,
so the clock here proves nothing and the statement count proves everything. This
is the same blind spot that produced 2607.15.1.
"""

from __future__ import annotations

from sqlalchemy import event, select

from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import Movie, Rating, Score, WatchHistory


def _library(factory, count: int) -> None:
    with factory() as session:
        for n in range(count):
            tmdb_id = 1000 + n
            session.add(
                Movie(tmdb_id=tmdb_id, title=f"F{n}", year=2000 + (n % 20), in_plex=True)
            )
            # Two ratings apiece, so the most-voted pick is actually exercised.
            session.add(Rating(movie_id=tmdb_id, source="tmdb", value=6.0, votes=100 + n))
            session.add(Rating(movie_id=tmdb_id, source="imdb", value=4.0, votes=10))
            if n % 3 == 0:
                session.add(
                    WatchHistory(movie_id=tmdb_id, plex_user="Dad", plays=2, completion_pct=0.9)
                )
        session.commit()


def _statements(factory, fn) -> int:
    engine = factory.kw["bind"]
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        seen.append(statement.lstrip().split()[0].upper())

    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return sum(1 for s in seen if s == "SELECT")


def test_scoring_does_not_read_the_database_once_per_film(factory, settings):
    """Ten films and eighty must cost the same number of reads.

    A per-film get, a per-film rating query or a lazily loaded score row makes the
    second number grow with the first — which is invisible here as time and is
    minutes of stalled scan against a hosted database.
    """
    thr = JunkThresholds()
    _library(factory, 10)
    junk.compute_and_store(factory, thr)  # warm: first pass inserts every Score row
    small = _statements(factory, lambda: junk.compute_and_store(factory, thr))

    _library_extra_start = 10
    with factory() as session:
        for n in range(_library_extra_start, 80):
            tmdb_id = 1000 + n
            session.add(
                Movie(tmdb_id=tmdb_id, title=f"F{n}", year=2000 + (n % 20), in_plex=True)
            )
            session.add(Rating(movie_id=tmdb_id, source="tmdb", value=6.0, votes=100 + n))
        session.commit()
    junk.compute_and_store(factory, thr)
    large = _statements(factory, lambda: junk.compute_and_store(factory, thr))

    assert small == large, f"reads grew from {small} to {large} between 10 and 80 films"
    assert large < 15, f"scoring a library took {large} reads"


def test_the_most_voted_rating_still_wins(factory, settings):
    """NEGATIVE CONTROL for the batched rating lookup.

    Batching replaced a per-film ``max(votes)`` with one grouped query, and what
    would quietly break is *which* rating survives. Asserted on the selection
    itself rather than on the resulting junk score, because Bayesian shrinkage
    pulls a 9-vote rating so far toward the prior that picking the wrong one
    barely moves the score — a test routed through the score passes under the bug.

    The reliable rating is written first so "keep whichever came last" fails, and
    a tie is included so "keep the first" is not silently equivalent to "keep the
    most voted".
    """
    with factory() as session:
        session.add(Movie(tmdb_id=7, title="Contested", year=2001, in_plex=True))
        session.add(Rating(movie_id=7, source="tmdb", value=8.0, votes=9000))
        session.add(Rating(movie_id=7, source="imdb", value=1.0, votes=9))
        # ...and the mirror image, whose reliable rating comes last, so "keep the
        # first" fails here. One direction alone is not a test: whichever way the
        # rows are written, one of the two wrong rules agrees with the right one.
        session.add(Movie(tmdb_id=10, title="Reversed", year=2001, in_plex=True))
        session.add(Rating(movie_id=10, source="imdb", value=2.0, votes=5))
        session.add(Rating(movie_id=10, source="tmdb", value=9.0, votes=8000))
        # A film whose two ratings are equally voted: the first must win, which is
        # what the per-film max() did.
        session.add(Movie(tmdb_id=9, title="Tied", year=2001, in_plex=True))
        session.add(Rating(movie_id=9, source="tmdb", value=7.0, votes=50))
        session.add(Rating(movie_id=9, source="imdb", value=2.0, votes=50))
        session.commit()

    with factory() as session:
        best = junk._best_ratings(session, [7, 9, 10])

    assert best[7] == (8.0, 9000)
    assert best[10] == (9.0, 8000)
    assert best[9] == (7.0, 50)


def test_a_film_with_no_ratings_is_still_scored(factory, settings):
    """The grouped lookup returns nothing for such a film, where the old per-film
    query returned ``(None, None)``. Both must mean the same thing — and must not
    be read as 'nobody has heard of it', which would propose deleting a library
    that TMDB simply hasn't reached yet."""
    with factory() as session:
        session.add(Movie(tmdb_id=8, title="Unrated", year=2001, in_plex=True))
        session.commit()

    assert junk.compute_and_store(factory, JunkThresholds()) == 1
    with factory() as session:
        row = session.scalars(select(Score).where(Score.movie_id == 8)).one()
        signals = {s["key"]: s for s in row.signals["signals"]}
    assert signals["rating"]["available"] is False
