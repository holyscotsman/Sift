"""The shadow diff — the eval that decides whether v2 is allowed to replace v1.

``shadow_diff`` is the only honest measure of the scorer's *judgement* that
exists, because it runs on the owner's real library rather than on cases picked
to prove a point. It was also entirely untested, which meant the numbers on the
one screen that decides the v1→v2 cutover were unverified.
"""

from __future__ import annotations

from sqlalchemy import event, func, select

from sift.analysis import junk, scoring_v2
from sift.config import JunkThresholds
from sift.db.models import Movie, Score, ScoreV2


def _seed(session, tmdb_id, title, *, v1=None, v1_band=None, v2=None, v2_band=None):
    """Put one film in the library, optionally with a v1 score, a v2 score, or both.

    Passing only one side is how the 'scored by one engine but not the other'
    case is built — a film added between the two scoring passes.
    """
    session.add(Movie(tmdb_id=tmdb_id, title=title, year=1999))
    if v1 is not None:
        signals = {"band": v1_band} if v1_band is not None else {}
        session.add(Score(movie_id=tmdb_id, junk_score=v1, signals=signals))
    if v2 is not None:
        session.add(ScoreV2(movie_id=tmdb_id, score=v2, band=v2_band or "keep", confidence=0.8))


def test_only_films_both_engines_scored_are_compared(factory):
    """A film v1 scored and v2 did not is not a disagreement — it is an absence.

    Counting it would report drift that no engine actually claimed, and the
    cutover decision rests on that count.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 603, "Both", v1=90.0, v1_band="junk", v2=10.0, v2_band="keep")
        _seed(session, 604, "V1 only", v1=90.0, v1_band="junk")
        _seed(session, 605, "V2 only", v2=90.0, v2_band="junk")
        session.commit()

        diffs, summary = junk.shadow_diff(session, thr)

    assert summary["compared"] == 1
    assert [d["tmdb_id"] for d in diffs] == [603]


def test_agreement_reports_nothing(factory):
    """NEGATIVE CONTROL: same band on both sides is silence, not a row.

    The scores differ (v1 is 0–100, v2 is its own scale) — only the *band* is
    comparable, and a diff keyed off the number would report every single film.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 603, "Agree", v1=90.0, v1_band="junk", v2=12.0, v2_band="junk")
        _seed(session, 604, "Agree too", v1=5.0, v1_band="keep", v2=99.0, v2_band="keep")
        session.commit()

        diffs, summary = junk.shadow_diff(session, thr)

    assert diffs == []
    assert summary == {
        "compared": 2,
        "disagreements": 0,
        "v2_stricter": 0,
        "v2_gentler": 0,
        "v2_abstained": 0,
    }


def test_direction_of_each_disagreement_is_counted_separately(factory):
    """keep→junk is v2 being stricter; junk→keep is v2 being gentler; anything→
    insufficient is v2 declining to answer.

    These three are the summary the cutover is read from, and collapsing them
    into one 'disagreements' number would hide the only thing that matters:
    whether v2 deletes more films than v1 or fewer.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 1, "Stricter", v1=10.0, v1_band="keep", v2=80.0, v2_band="junk")
        _seed(session, 2, "Stricter too", v1=50.0, v1_band="borderline", v2=80.0, v2_band="junk")
        _seed(session, 3, "Gentler", v1=90.0, v1_band="junk", v2=10.0, v2_band="keep")
        _seed(session, 4, "Abstained", v1=90.0, v1_band="junk",
              v2=0.0, v2_band=scoring_v2.INSUFFICIENT)
        session.commit()

        _, summary = junk.shadow_diff(session, thr)

    assert summary["compared"] == 4
    assert summary["disagreements"] == 4
    assert summary["v2_stricter"] == 2
    assert summary["v2_gentler"] == 1
    assert summary["v2_abstained"] == 1


def test_abstention_is_never_scored_as_a_direction(factory):
    """'insufficient' is not a band on the keep→borderline→junk ladder, so an
    ordering comparison against it is meaningless.

    Ranked naively it sorts below 'keep' and every abstention would be reported
    as v2 going *gentler* — the diff would claim v2 wants to keep films it has
    explicitly refused to judge.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 1, "From keep", v1=10.0, v1_band="keep",
              v2=0.0, v2_band=scoring_v2.INSUFFICIENT)
        _seed(session, 2, "From junk", v1=90.0, v1_band="junk",
              v2=0.0, v2_band=scoring_v2.INSUFFICIENT)
        session.commit()

        _, summary = junk.shadow_diff(session, thr)

    assert summary["v2_abstained"] == 2
    assert summary["v2_stricter"] == 0
    assert summary["v2_gentler"] == 0


def test_the_stored_v1_band_wins_over_recomputing_it(factory):
    """v1's band is read from its stored signals, not recomputed from today's
    thresholds — and the difference is the whole point.

    A film scored 45 under a borderline cutoff of 40 was 'borderline' when v1
    judged it. Recomputing under a later cutoff of 50 would relabel it 'keep'
    and manufacture a disagreement with v2 that neither engine ever had. The
    diff must compare what the engines said, not what they would say now.
    """
    with factory() as session:
        _seed(session, 603, "Reclassified", v1=45.0, v1_band="borderline",
              v2=45.0, v2_band="borderline")
        session.commit()

        moved = JunkThresholds(borderline_cutoff=50.0, junk_cutoff=70.0)
        diffs, summary = junk.shadow_diff(session, moved)

    assert diffs == []
    assert summary["disagreements"] == 0


def test_a_v1_row_with_no_stored_band_falls_back_to_the_thresholds(factory):
    """NEGATIVE CONTROL for the above: rows written before bands were stored have
    empty signals, and those must still be comparable rather than silently
    skipped — otherwise the diff quietly shrinks to only the newest scans.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 603, "No stored band", v1=90.0, v2=10.0, v2_band="keep")
        session.commit()

        diffs, summary = junk.shadow_diff(session, thr)

    assert summary["disagreements"] == 1
    assert diffs[0]["v1_band"] == "junk"  # 90 ≥ junk_cutoff 60, recomputed


def test_biggest_disagreements_are_listed_first(factory):
    """Ordered by the size of the numeric gap, so the page opens on the films
    where the two engines are furthest apart — those are what a human can
    actually adjudicate. Ties break on tmdb_id so the same library produces the
    same list on every load.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 10, "Small gap", v1=61.0, v1_band="junk", v2=50.0, v2_band="keep")
        _seed(session, 20, "Huge gap", v1=99.0, v1_band="junk", v2=1.0, v2_band="keep")
        _seed(session, 30, "Middling", v1=80.0, v1_band="junk", v2=20.0, v2_band="keep")
        session.commit()

        diffs, _ = junk.shadow_diff(session, thr)

    assert [d["tmdb_id"] for d in diffs] == [20, 30, 10]


def test_equal_gaps_come_back_in_a_fixed_order(factory):
    """NEGATIVE CONTROL for the ordering pin: identical gaps must not be left in
    whatever order the underlying set happened to yield, or the same library
    reorders itself between two loads and a reviewer loses their place.

    The ids are chosen so that ``list(set(ids)) != sorted(ids)`` — a set of small
    ints iterates in hash order, which for tidy ids like 1/2/3 *is* sorted, and a
    fixture built from those would pass even with the ordering removed entirely.
    These were picked because their set order genuinely differs.

    Two things deliver the guarantee independently — ``sorted(shared)`` upstream
    and the tmdb_id tie-break in ``_diff_sort_key`` — so removing either one on
    its own leaves this green. Verified: removing *both* turns it red. The pin is
    on the contract, not on which of the two mechanisms happens to be carrying it.
    """
    thr = JunkThresholds()
    scrambled = [2653, 1236, 3235, 396, 594]
    assert list(set(scrambled)) != sorted(scrambled), "fixture no longer scrambles — repick"

    with factory() as session:
        for tmdb_id in scrambled:
            _seed(session, tmdb_id, f"Film {tmdb_id}", v1=90.0, v1_band="junk",
                  v2=10.0, v2_band="keep")
        session.commit()

        diffs, _ = junk.shadow_diff(session, thr)

    assert [d["tmdb_id"] for d in diffs] == sorted(scrambled)


def test_the_limit_keeps_the_biggest_disagreements_not_the_first_found(factory):
    """Truncation happens after ranking. Cutting the list before sorting would
    return whichever films happened to come back first — an arbitrary sample
    presented as 'the worst disagreements', which is exactly the way a shadow
    eval lies.
    """
    thr = JunkThresholds()
    with factory() as session:
        # The gap *grows* with the id, so the films found first are the least
        # interesting ones. If the limit were applied before the ranking this
        # would return 100-102 (the three smallest gaps) instead of 107-109.
        for i in range(10):
            _seed(session, 100 + i, f"Film {i}", v1=60.0 + i * 4, v1_band="junk",
                  v2=50.0 - i * 4, v2_band="keep")
        session.commit()

        diffs, summary = junk.shadow_diff(session, thr, limit=3)

    assert summary["disagreements"] == 10  # the summary counts everything
    assert len(diffs) == 3  # the list is a page
    assert [d["tmdb_id"] for d in diffs] == [109, 108, 107]


def test_titles_are_attached_to_the_page_not_the_whole_library(factory):
    """The rows carry title and year for display, hydrated for the page actually
    returned rather than for every disagreement found.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 603, "The Matrix", v1=90.0, v1_band="junk", v2=10.0, v2_band="keep")
        session.commit()

        diffs, _ = junk.shadow_diff(session, thr)

    assert diffs[0]["title"] == "The Matrix"
    assert diffs[0]["year"] == 1999


def test_removing_a_film_removes_it_from_the_diff(factory):
    """NEGATIVE CONTROL for the hydration step: a deleted film leaves no row.

    ``shadow_diff`` guards its title lookup with ``if movie is not None``, which
    reads like it handles orphaned score rows. It does not need to: both score
    tables are ``ON DELETE CASCADE`` on ``movies.tmdb_id`` and SQLite runs with
    ``PRAGMA foreign_keys=ON`` (``db/session.py:48``), so the scores go with the
    film and an orphan cannot be constructed through the database at all. This
    pins the behaviour that actually exists — deleted films vanish from the diff
    rather than appearing as untitled rows — and records that the guard is
    defensive, not load-bearing.
    """
    thr = JunkThresholds()
    with factory() as session:
        _seed(session, 603, "Doomed", v1=90.0, v1_band="junk", v2=10.0, v2_band="keep")
        _seed(session, 604, "Survivor", v1=90.0, v1_band="junk", v2=10.0, v2_band="keep")
        session.commit()

        session.execute(Movie.__table__.delete().where(Movie.tmdb_id == 603))
        session.commit()

        diffs, summary = junk.shadow_diff(session, thr)

        assert summary["compared"] == 1
        assert [d["tmdb_id"] for d in diffs] == [604]
        assert session.scalar(select(func.count()).select_from(Score)) == 1


def test_the_diff_costs_the_same_on_a_big_library_as_a_small_one(factory):
    """Regression pin on the stated cost. Both score tables are read whole and
    joined in memory; titles are chunk-loaded for the page only. The statement
    count is therefore a small constant and does not grow with the library —
    which on hosted Postgres, where every statement is a round trip, is the
    difference between a page that loads and one that times out.

    Measured at three for both a five-film and a four-hundred-film library: two
    whole-table score reads plus one chunked title hydrate. The docstring
    claimed two and had forgotten the hydrate; it now says three.
    """
    thr = JunkThresholds()
    engine = factory.kw["bind"]

    def count(n_films: int) -> int:
        with factory() as session:
            session.execute(ScoreV2.__table__.delete())
            session.execute(Score.__table__.delete())
            session.execute(Movie.__table__.delete())
            for i in range(n_films):
                _seed(session, 1000 + i, f"Film {i}", v1=90.0, v1_band="junk",
                      v2=10.0, v2_band="keep")
            session.commit()

            statements = {"n": 0}

            @event.listens_for(engine, "before_cursor_execute")
            def _tick(*_a, **_kw):
                statements["n"] += 1

            try:
                junk.shadow_diff(session, thr, limit=400)
            finally:
                event.remove(engine, "before_cursor_execute", _tick)
            return statements["n"]

    small, large = count(5), count(400)
    assert small == large, f"{small} statements for 5 films, {large} for 400 — per-film work?"
    assert large == 3, f"{large} statements, not the 2 score reads + 1 title hydrate"
