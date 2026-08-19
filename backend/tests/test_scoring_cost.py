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


def test_scoring_never_reads_the_wide_columns(factory, settings):
    """Egress pin, not a round-trip pin.

    Scoring walks the whole library every scan. `select(Movie)` ships all
    twenty-seven columns — `overview`, `poster_url`, `genres`, `keywords` — none
    of which affects a score, and together they dwarf the ones that do. Worse,
    `select(Score)` and `select(ScoreV2)` shipped a JSON blob per film purely to
    decide insert-versus-update, then threw it away.

    On the SQLite these tests run against that is free, which is exactly why it
    survived. On a hosted database it is the largest read the scan performs, and
    it is metered: a free tier's monthly transfer allowance disappears in a week.
    """
    from sqlalchemy import event

    from sift.analysis import junk
    from sift.db.models import Movie

    with factory() as session:
        for i in range(200):
            session.add(
                Movie(
                    tmdb_id=9_000 + i,
                    title=f"Film {i}",
                    in_plex=True,
                    overview="x" * 600,
                    poster_url="https://image.tmdb.org/t/p/w342/" + "y" * 40,
                    genres=["Drama", "Thriller"],
                    keywords=["one", "two", "three"],
                )
            )
        session.commit()

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        written = junk.compute_and_store(factory, settings.junk)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    # NEGATIVE CONTROL: the work must actually have happened. A no-op scorer
    # reads no wide columns at all and would pass every assertion below.
    assert written == 200

    reads = [s for s in seen if s.upper().startswith("SELECT")]
    for column, table in (
        ("movies.overview", "movies"),
        ("movies.poster_url", "movies"),
        ("movies.genres", "movies"),
        ("scores.signals", "scores"),
        ("scores_v2.signals", "scores_v2"),
    ):
        offenders = [s for s in reads if column in s]
        assert not offenders, f"scoring read {column} it never uses: {offenders[0][:140]}"
        assert any(table in s for s in reads), f"nothing read {table} at all — is it still running?"


def _scored_library(factory, count: int, *, candidates: int) -> None:
    """`count` scored films, of which only `candidates` are removal candidates."""
    with factory() as session:
        for n in range(count):
            tmdb_id = 5_000 + n
            session.add(
                Movie(
                    tmdb_id=tmdb_id,
                    title=f"Film {n}",
                    year=2000,
                    in_plex=True,
                    is_kids=False,
                    keep_override=False,
                    overview="x" * 600,
                    poster_url="https://image.tmdb.org/t/p/w342/" + "y" * 40,
                )
            )
            flagged = n < candidates
            session.add(
                Score(
                    movie_id=tmdb_id,
                    # Deliberately *ascending* with the id, so rank order and id
                    # order disagree. Seed them in agreement and any test of the
                    # ranking passes by coincidence — an `IN` query returning its
                    # own order would look correct.
                    junk_score=50.0 + n if flagged else 5.0,
                    signals={
                        "verdict": "neutral",
                        "band": "junk" if flagged else "keep",
                        "signals": [{"name": f"s{i}", "value": i} for i in range(6)],
                    },
                )
            )
        session.commit()


def test_the_junk_page_does_not_hydrate_the_whole_library(factory):
    """The Junk queue is asked for on every visit to the screen.

    Deciding candidacy needs a score and a verdict; *rendering* a candidate needs
    the film. Selecting both at once meant every non-kids title arrived fully
    hydrated — all thirty-one columns of `movies`, `overview` and `poster_url`
    included — so that a couple of hundred could be shown and the rest thrown
    away. On a byte-metered database that discard is the whole cost of the page.
    """
    thr = JunkThresholds()
    _scored_library(factory, 300, candidates=40)

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        with factory() as session:
            rows = junk.candidates(session, thr, limit=20)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    # NEGATIVE CONTROL, inline: a query that returned nothing reads no wide
    # columns at all and would satisfy every assertion below.
    assert len(rows) == 20

    reads = [s for s in seen if s.upper().startswith("SELECT")]
    wide = [s for s in reads if "movies.overview" in s]
    assert len(wide) == 1, f"{len(wide)} statements read the wide movie columns"
    # And the one that does is bounded by the winners rather than the library.
    assert " IN (" in wide[0], f"the hydration read is unbounded: {wide[0][:160]}"


def test_the_same_films_come_back_in_the_same_order(factory):
    """NEGATIVE CONTROL: reading less must not mean deciding differently.

    Two passes can disagree with one in three ways — a different filter, a
    different ranking, or an `IN` query quietly returning its own order. Compare
    against the whole set, computed the slow way.
    """
    thr = JunkThresholds()
    _scored_library(factory, 120, candidates=30)

    with factory() as session:
        rows = junk.candidates(session, thr, limit=10)

        reference = [
            (m, s)
            for m, s in session.execute(
                select(Movie, Score)
                .join(Score, Score.movie_id == Movie.tmdb_id)
                .where(
                    Movie.in_plex.is_(True),
                    Movie.is_kids.is_(False),
                    Movie.keep_override.is_(False),
                )
                .order_by(Score.junk_score.desc())
            )
            if junk._is_candidate(s, thr)
        ][:10]

    assert [m.tmdb_id for m, _ in rows] == [m.tmdb_id for m, _ in reference]
    assert [s.junk_score for _, s in rows] == [s.junk_score for _, s in reference]
    # Ranked, not merely filtered.
    assert [s.junk_score for _, s in rows] == sorted(
        (s.junk_score for _, s in rows), reverse=True
    )


def test_a_protect_verdict_still_keeps_a_low_scorer_out(factory):
    """NEGATIVE CONTROL: the verdict overlay must survive the split.

    The classifier's verdict lives inside the `signals` JSON and is the one part
    of the decision that could not move into SQL. A refactor that dropped it
    would flag protected titles — cult classics and US theatrical releases — for
    removal, which is the exact failure the overlay exists to prevent.
    """
    thr = JunkThresholds()
    with factory() as session:
        for n, verdict in enumerate(("protect", "remove", "neutral")):
            tmdb_id = 8_000 + n
            session.add(Movie(tmdb_id=tmdb_id, title=verdict, in_plex=True))
            session.add(
                Score(
                    movie_id=tmdb_id,
                    # Low enough that only the verdict can put it in the queue,
                    # and high enough that only the verdict can keep it out.
                    junk_score=95.0 if verdict == "protect" else 1.0,
                    signals={"verdict": verdict, "band": "junk"},
                )
            )
        session.commit()

        titles = {m.title for m, _ in junk.candidates(session, thr, limit=50)}

    assert "protect" not in titles, "a protected title reached the removal queue"
    assert "remove" in titles, "a remove verdict was ignored"
    assert "neutral" not in titles, "a low-scoring neutral title was flagged anyway"


def test_counting_the_flagged_titles_fetches_no_films(factory):
    """The header badge is a number. It was produced by building the list.

    `/api/status` is polled for as long as a tab is open, and its junk figure came
    from `len(candidates(...))` with a limit of ten thousand — so counting the
    flagged titles hydrated every one of them, poster URL and overview included,
    to take the length of the result.
    """
    thr = JunkThresholds()
    _scored_library(factory, 300, candidates=40)

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        with factory() as session:
            count = len(junk.candidate_ids(session, thr, limit=10_000))
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert count == 40  # the work happened
    wide = [s for s in seen if "movies.overview" in s or "movies.poster_url" in s]
    assert not wide, f"counting the queue fetched films: {wide[0][:140]}"


def test_the_count_and_the_list_agree(factory):
    """NEGATIVE CONTROL: a cheaper count that counts something else is worse than
    an expensive one.

    The badge and the page must never disagree — a header promising forty titles
    over a screen showing thirty-nine is a bug report waiting to happen, and the
    two now walk different code paths.
    """
    thr = JunkThresholds()
    _scored_library(factory, 200, candidates=25)

    with factory() as session:
        ids = junk.candidate_ids(session, thr, limit=10_000)
        rows = junk.candidates(session, thr, limit=10_000)

    assert len(ids) == len(rows) == 25
    assert ids == [m.tmdb_id for m, _ in rows]
