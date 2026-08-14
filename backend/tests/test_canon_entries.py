"""The validated canon: seeding, budgeted resolution, and the junk shield.

The canon is a fact about cinema rather than about this household, which is what
lets it answer both of Sift's questions at once. Unowned canon is something to
acquire; owned canon is something the junk queue must leave alone. These pin the
second, because that is the direction where being wrong deletes a film.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import CanonEntry, Movie, Score
from sift.services import canon_entries

_FILE = {
    "version": "test-1",
    "titles": [
        {"title": "Seven Samurai", "year": 1954, "imdb_id": "tt0047478", "tier": 1,
         "sources": ["criterion"], "spine": 2, "rating": 8.6, "votes": 300000},
        {"title": "Solaris", "year": 1972, "imdb_id": "tt0069293", "tier": 2,
         "sources": ["criterion"], "rating": 8.0, "votes": 100000},
        {"title": "Repo Man", "year": 1984, "imdb_id": "tt0087995", "tier": 3,
         "sources": ["cult"], "rating": 6.9, "votes": 40000},
        {"title": "Famous But Dull", "year": 2011, "imdb_id": "tt0000004", "tier": 4,
         "sources": ["imdb_wr"], "rating": 6.1, "votes": 90000},
        {"title": "No Id Here", "year": 1930, "tier": 2, "sources": ["award"]},
    ],
}


@pytest.fixture
def canon_file(monkeypatch):
    monkeypatch.setattr(canon_entries, "load_file", lambda: _FILE)
    return _FILE


def test_seeding_is_idempotent(factory, canon_file):
    """A scan runs this every time. Seeding twice must not double the canon."""
    with factory() as session:
        assert canon_entries.seed(session) == 5
    with factory() as session:
        assert canon_entries.seed(session) == 0
        assert session.scalar(select(func.count()).select_from(CanonEntry)) == 5


def test_reseeding_keeps_resolutions_already_paid_for(factory, canon_file):
    """Resolution costs API budget spread over many scans. A reseed that discarded
    it would pay for the same lookups twice, and the coverage figure would walk
    backwards every time the file was refreshed."""
    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 1)).one()
        canon_entries.apply_resolution(session, {entry.id: 346})

    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 1)).one()
        assert entry.tmdb_id == 346
        assert entry.review_status == "resolved"


def test_the_strongest_claims_resolve_first(factory, canon_file):
    """The budget covers a slice of the list per scan, so which slice matters. A
    tier-1 entry earns its place in the library sooner than a tier-4 one."""
    with factory() as session:
        canon_entries.seed(session)
        pending = canon_entries.pending_resolution(session, limit=3)
    assert [row[2] for row in pending] == ["Seven Samurai", "Solaris", "No Id Here"]


def test_a_miss_is_an_attempt_not_a_verdict(factory, canon_file):
    """TMDB failing to find a title today does not make it un-canonical. It is
    retried until the ceiling, then set aside so a few stubborn entries cannot
    eat the budget on every scan for ever."""
    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 1)).one()
        for attempt in range(canon_entries.MAX_RESOLVE_ATTEMPTS):
            _found, exhausted = canon_entries.apply_resolution(session, {entry.id: None})
            session.expire_all()
            still = session.get(CanonEntry, entry.id)
            expected = attempt + 1 >= canon_entries.MAX_RESOLVE_ATTEMPTS
            assert (still.review_status == "unresolvable") is expected
        assert exhausted == 1
        # And it is no longer offered for resolution.
        assert all(row[0] != entry.id for row in canon_entries.pending_resolution(session, 10))


def _own(session, tmdb_id: int, title: str, *, votes: int) -> None:
    from sift.db.models import Rating

    session.add(Movie(tmdb_id=tmdb_id, title=title, year=1954, in_plex=True))
    session.add(Rating(movie_id=tmdb_id, source="tmdb", value=8.5, votes=votes))


def test_an_owned_tier_two_canon_film_is_shielded_from_the_junk_queue(factory, canon_file):
    """The shield. A curated-canon film nobody has played is still not junk: the
    Missing page would be telling you to acquire the very thing the Junk page
    proposed deleting."""
    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 2)).first()
        _own(session, 555, "Solaris", votes=40)  # obscure by vote count alone
        session.commit()
        canon_entries.apply_resolution(session, {entry.id: 555})

    junk.compute_and_store(factory, JunkThresholds())
    with factory() as session:
        signals = {
            s["key"]: s
            for s in session.scalars(select(Score).where(Score.movie_id == 555)).one().signals[
                "signals"
            ]
        }
    # Recognition is floored for canon, so obscurity cannot condemn it.
    assert signals["recognition"]["contribution"] <= 0.25, signals["recognition"]


def test_a_tier_four_canon_film_can_still_be_flagged(factory, canon_file):
    """NEGATIVE CONTROL, and the reason the shield stops at tier 3.

    Tier 4 is fame-fill. A famous film nobody in the house watches is precisely
    what the junk queue exists to surface, so shielding it would empty the queue
    of its most useful entries.
    """
    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 4)).one()
        _own(session, 777, "Famous But Dull", votes=40)
        session.commit()
        canon_entries.apply_resolution(session, {entry.id: 777})

    with factory() as session:
        assert 777 not in canon_entries.protected_tmdb_ids(session)
        assert 555 not in canon_entries.protected_tmdb_ids(session)  # unresolved tier 2


def test_coverage_reports_what_it_does_not_yet_know(factory, canon_file):
    """A coverage figure that hid the unresolved remainder would read as complete
    while most of the canon had never been looked up."""
    with factory() as session:
        canon_entries.seed(session)
        entry = session.scalars(select(CanonEntry).where(CanonEntry.tier == 1)).one()
        _own(session, 346, "Seven Samurai", votes=300000)
        session.commit()
        canon_entries.apply_resolution(session, {entry.id: 346})
        counts = canon_entries.coverage(session)

    assert counts["total"] == 5
    assert counts["owned"] == 1
    assert counts["resolved"] == 1
    assert counts["unresolved"] == 4
    assert counts["owned"] + counts["unresolved"] <= counts["total"]


def test_the_shipped_canon_file_is_the_one_that_was_validated(factory):
    """The data file itself, not a fixture. Ten thousand entries, every one tiered,
    no duplicate ids — the properties the validation pass established, checked
    here so a corrupted or truncated file fails loudly rather than seeding a
    quietly smaller canon."""
    data = canon_entries.load_file()
    titles = data["titles"]
    assert len(titles) == 10_000
    assert data["version"]
    assert all(t.get("tier") in (1, 2, 3, 4) for t in titles)
    assert all(t.get("title") for t in titles)
    ids = [t["imdb_id"] for t in titles if t.get("imdb_id")]
    assert len(ids) == len(set(ids))
    assert len(ids) / len(titles) > 0.95


def test_seeding_the_canon_does_not_cost_a_statement_per_title(factory, canon_file, monkeypatch):
    """Ten thousand rows added one at a time is ten thousand round trips on the
    first scan — free on the SQLite this runs on, close to a minute against the
    hosted database, and indistinguishable from a stall while it happens. The same
    lesson as 2607.15.1, and this is the largest single insert the app performs."""
    from sqlalchemy import event

    many = {
        "version": "bulk-1",
        "titles": [
            {
                "title": f"Film {n}",
                "year": 1990 + (n % 30),
                "imdb_id": f"tt{n:07d}",
                "tier": 1 + (n % 4),
            }
            for n in range(600)
        ],
    }
    monkeypatch.setattr(canon_entries, "load_file", lambda: many)

    engine = factory.kw["bind"]
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    try:
        with factory() as session:
            assert canon_entries.seed(session) == 600
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(statements) < 20, f"{len(statements)} statements for 600 titles"
