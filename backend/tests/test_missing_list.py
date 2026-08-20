"""The unified Missing list: what it subtracts, how it ranks, and what sticks.

One list, endlessly paged, built from the shipped canon. Three things come off
it — what you own, what you have already asked for, and what you have said no to
— and the third is the one that has to survive a restart, a rescan and a rebuild
of the canon file, because "remembered forever" was the requirement.

The pins here are mostly about *subtraction*, because that is the direction where
being wrong is invisible: a title wrongly kept on the list is annoying and
obvious, a title wrongly dropped from it is silently never seen again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from sift.analysis import canon_missing
from sift.db.models import (
    Action,
    ActionStatus,
    ActionType,
    CanonEntry,
    IgnoredTitle,
    Movie,
)
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _entry(tmdb_id: int, title: str, *, tier: int = 1, votes: int = 1000) -> CanonEntry:
    return CanonEntry(
        imdb_id=f"tt{tmdb_id:07d}",
        title=title,
        year=1999,
        tier=tier,
        sources=["award"],
        rating=8.0,
        votes=votes,
        tmdb_id=tmdb_id,
        review_status="resolved",
    )


def _seed(session) -> None:
    session.add_all(
        [
            _entry(1, "Owned Already"),
            _entry(2, "Already Requested"),
            _entry(3, "Said No To"),
            _entry(4, "Still Available"),
        ]
    )
    session.add(Movie(tmdb_id=1, title="Owned Already", in_plex=True))
    session.add(
        Action(
            type=ActionType.ADD,
            movie_tmdb_id=2,
            status=ActionStatus.EXECUTED,
            dry_run=False,
        )
    )
    session.add(IgnoredTitle(tmdb_id=3, title="Said No To", source="missing"))
    session.commit()


def test_the_list_subtracts_owned_requested_and_refused(factory):
    """All three subtractions at once, because they interact: a title can only be
    counted as hidden if it was not already excluded for being owned."""
    with factory() as session:
        _seed(session)
        rows, total = canon_missing.missing(session)
        assert [r.tmdb_id for r in rows] == [4]
        assert total == 1
        # The hidden titles are accounted for rather than silently gone. Owned is
        # not among them — you have it, so it was never a candidate.
        assert canon_missing.hidden(session) == {"requested": 1, "ignored": 1}


def test_NEGATIVE_CONTROL_a_staged_add_leaves_the_title_on_the_list(factory):
    """NEGATIVE CONTROL: dry-run adds reached nothing, so the film is still
    genuinely missing. If this passed, a staged instance would quietly empty its
    own Missing list without acquiring a single film."""
    with factory() as session:
        session.add_all([_entry(10, "Staged"), _entry(11, "Proposed"), _entry(12, "Failed")])
        session.add(
            Action(
                type=ActionType.ADD,
                movie_tmdb_id=10,
                status=ActionStatus.EXECUTED,
                dry_run=True,
            )
        )
        session.add(
            Action(
                type=ActionType.ADD,
                movie_tmdb_id=11,
                status=ActionStatus.PROPOSED,
                dry_run=False,
            )
        )
        session.add(
            Action(
                type=ActionType.ADD,
                movie_tmdb_id=12,
                status=ActionStatus.FAILED,
                dry_run=False,
            )
        )
        session.commit()
        rows, _ = canon_missing.missing(session)
        assert {r.tmdb_id for r in rows} == {10, 11, 12}
        assert canon_missing.hidden(session)["requested"] == 0


def test_NEGATIVE_CONTROL_an_unresolved_entry_is_unknown_not_missing(factory):
    """NEGATIVE CONTROL: an entry with no TMDB id cannot be compared with the
    library at all, so calling it missing is a guess. It is excluded instead —
    which is why the coverage figure reports its unresolved remainder."""
    with factory() as session:
        unresolved = _entry(99, "No Id Yet")
        unresolved.tmdb_id = None
        session.add_all([unresolved, _entry(100, "Resolved")])
        session.commit()
        rows, total = canon_missing.missing(session)
        assert [r.tmdb_id for r in rows] == [100]
        assert total == 1


def test_the_strongest_claim_leads_and_the_order_is_total(factory):
    """Tier first, fame second, id last. The id term is not decoration: without a
    total order two equally famous titles swap places between requests, and paging
    then skips one of them for good."""
    with factory() as session:
        # Inserted with the tied pair *backwards*. SQLite hands back rowid order
        # when nothing else decides, so seeding 6 before 7 would satisfy the
        # assertion below even with the tie-break deleted — the pin would prove
        # nothing about the clause it exists to protect.
        session.add_all(
            [
                _entry(5, "Weak but famous", tier=4, votes=900_000),
                _entry(7, "Strong, tied fame", tier=1, votes=1_000),
                _entry(6, "Strong, less famous", tier=1, votes=1_000),
                _entry(8, "Strong, most famous", tier=1, votes=50_000),
            ]
        )
        session.commit()
        rows, _ = canon_missing.missing(session)
        assert [r.tmdb_id for r in rows] == [8, 6, 7, 5]


def test_paging_covers_the_list_without_repeating_or_skipping(factory):
    """The list is meant to be scrolled forever, so the pages have to tile. A
    ranking without a total order passes the first assertion and fails this one."""
    with factory() as session:
        session.add_all([_entry(200 + i, f"Film {i}", votes=1_000) for i in range(10)])
        session.commit()
        first, total = canon_missing.missing(session, limit=4, offset=0)
        second, _ = canon_missing.missing(session, limit=4, offset=4)
        third, _ = canon_missing.missing(session, limit=4, offset=8)
        seen = [r.tmdb_id for r in first + second + third]
        assert total == 10
        assert len(set(seen)) == 10 and len(seen) == 10


def test_reading_a_page_costs_the_same_two_statements_at_any_size(factory):
    """Round trips are free on SQLite and dominant on hosted Postgres, so the
    thing worth pinning is the statement *count*, not the clock. Two: the page and
    its remainder. The three subtractions are EXISTS clauses inside those, not
    extra queries — write one of them as a Python filter and this blows up.
    """
    with factory() as session:
        session.add_all([_entry(300 + i, f"Film {i}") for i in range(50)])
        session.commit()

    engine = factory.kw["bind"]
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_a, **_kw):
        statements["n"] += 1

    try:
        with factory() as session:
            canon_missing.missing(session, limit=50)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # Exactly two, not "a handful": pulling one of the three subtractions into
    # Python costs precisely one more statement, and a bound of three would let
    # that through.
    assert statements["n"] == 2, f"{statements['n']} statements for one page"


def test_ignoring_a_title_removes_it_and_taking_it_back_restores_it(client):
    """The full round trip through HTTP, because the endpoint is where a real
    mis-click happens."""
    c, factory = client
    with factory() as session:
        session.add_all([_entry(20, "Keeper"), _entry(21, "Not For Me")])
        session.commit()

    body = c.get("/api/missing/suggestions").json()
    assert {i["tmdb_id"] for i in body["items"]} == {20, 21}

    said_no = c.post("/api/missing/ignore", json={"tmdb_id": 21, "title": "Not For Me"})
    assert said_no.status_code == 200
    body = c.get("/api/missing/suggestions").json()
    assert [i["tmdb_id"] for i in body["items"]] == [20]
    assert body["ignored_total"] == 1

    listed = c.get("/api/missing/ignored").json()
    assert listed["total"] == 1 and listed["items"][0]["tmdb_id"] == 21

    assert c.delete("/api/missing/ignore/21").json() == {"removed": True}
    body = c.get("/api/missing/suggestions").json()
    assert {i["tmdb_id"] for i in body["items"]} == {20, 21}


def test_ignoring_twice_is_not_an_error_and_does_not_duplicate(client):
    """Double-clicking a button is not a second decision. A primary key would
    raise on the second insert if this were written as a blind add."""
    c, factory = client
    with factory() as session:
        session.add(_entry(30, "Nope"))
        session.commit()

    first = c.post("/api/missing/ignore", json={"tmdb_id": 30, "title": "Nope"})
    second = c.post("/api/missing/ignore", json={"tmdb_id": 30, "title": "Nope"})
    assert first.status_code == 200 and second.status_code == 200
    with factory() as session:
        assert len(list(session.scalars(select(IgnoredTitle)))) == 1


def test_NEGATIVE_CONTROL_taking_back_a_refusal_that_was_never_made(client):
    """NEGATIVE CONTROL: deleting nothing must report that it deleted nothing,
    not report success. A blanket ``{"removed": True}`` would pass every other
    test in this file."""
    c, _ = client
    assert c.delete("/api/missing/ignore/12345").json() == {"removed": False}


def test_a_refusal_outlives_the_canon_row_it_was_made_against(factory):
    """The refusal is about the *film*, not about one list's opinion of it. Rebuild
    the canon from a new file — new row ids, same TMDB ids — and the answer has to
    hold, or every list refresh resurrects everything the owner already dismissed.
    """
    with factory() as session:
        session.add(_entry(40, "Dismissed Once"))
        session.add(IgnoredTitle(tmdb_id=40, title="Dismissed Once"))
        session.commit()

    with factory() as session:
        for row in session.scalars(select(CanonEntry)):
            session.delete(row)
        session.commit()
        session.add(_entry(40, "Dismissed Once"))  # reseeded from a newer file
        session.commit()
        rows, total = canon_missing.missing(session)
        assert rows == [] and total == 0
