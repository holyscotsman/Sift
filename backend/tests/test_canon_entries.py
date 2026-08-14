"""The validated canon: seeding, budgeted resolution, and the junk shield.

The canon is a fact about cinema rather than about this household, which is what
lets it answer both of Sift's questions at once. Unowned canon is something to
acquire; owned canon is something the junk queue must leave alone. These pin the
second, because that is the direction where being wrong deletes a film.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import CanonEntry, Movie, Score
from sift.main import create_app
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
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


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


def _resolve_all(factory) -> None:
    """Give every seeded entry a tmdb_id, as resolution eventually would."""
    with factory() as session:
        entries = list(session.scalars(select(CanonEntry)))
        canon_entries.apply_resolution(
            session, {e.id: 1000 + i for i, e in enumerate(entries)}
        )


def test_unresolved_canon_is_not_reported_as_missing(factory, canon_file):
    """An entry with no tmdb_id is not "missing", it is *unknown*.

    The canon arrives keyed by IMDb id and the library by TMDB id, so an
    unresolved entry cannot be compared with anything. Listing it as missing would
    invite you to acquire a film you may already own — the exact failure the
    coverage endpoint's unresolved count exists to warn about.
    """
    from sift.analysis import canon_missing

    with factory() as session:
        canon_entries.seed(session)
        rows, total = canon_missing.missing(session)
    assert rows == [] and total == 0


def test_missing_canon_is_ranked_by_tier_then_fame(factory, canon_file):
    """The canon's own judgement leads; fame only breaks ties inside a tier. A
    famous tier-4 title must not outrank an obscure tier-1 one — that would invert
    the whole point of tiering."""
    from sift.analysis import canon_missing

    with factory() as session:
        canon_entries.seed(session)
    _resolve_all(factory)

    with factory() as session:
        rows, total = canon_missing.missing(session)

    assert total == 5
    assert [r.tier for r in rows] == sorted(r.tier for r in rows)
    assert rows[0].title == "Seven Samurai"  # tier 1, most votes


def test_owning_a_canon_film_removes_it_from_the_missing_list(factory, canon_file):
    """The list is canon minus the library. Owning one must take it off."""
    from sift.analysis import canon_missing

    with factory() as session:
        canon_entries.seed(session)
    _resolve_all(factory)

    with factory() as session:
        first = canon_missing.missing(session)[0][0]
        session.add(Movie(tmdb_id=first.tmdb_id, title=first.title, in_plex=True))
        session.commit()
        rows, total = canon_missing.missing(session)

    assert total == 4
    assert first.tmdb_id not in {r.tmdb_id for r in rows}


def test_paging_the_missing_list_is_stable(factory, canon_file):
    """NEGATIVE CONTROL for the id in the sort key. Two equally famous titles with
    no total order swap places between requests, and paging then skips one
    entirely — the reader never sees it and never knows."""
    from sift.analysis import canon_missing

    with factory() as session:
        canon_entries.seed(session)
        # Four entries tied on tier and votes: only the id can order them. Written
        # in *descending* id order on purpose — inserted ascending, the database's
        # natural row order already matches the intended one and a missing
        # tie-break is invisible. Running the query twice proves nothing either:
        # SQLite is stable within a process, which is exactly how this class of
        # bug survives until it reaches Postgres.
        for n in reversed(range(4)):
            session.add(
                CanonEntry(
                    imdb_id=f"tt900000{n}", title=f"Tied {n}", year=2000,
                    tier=1, sources=["award"], votes=500, tmdb_id=9000 + n,
                    review_status="resolved",
                )
            )
        session.commit()

    with factory() as session:
        first_pass = [r.tmdb_id for r in canon_missing.missing(session, limit=100)[0]]
    with factory() as session:
        second_pass = [r.tmdb_id for r in canon_missing.missing(session, limit=100)[0]]
    assert first_pass == second_pass

    with factory() as session:
        page1 = [r.tmdb_id for r in canon_missing.missing(session, limit=2, offset=0)[0]]
        page2 = [r.tmdb_id for r in canon_missing.missing(session, limit=2, offset=2)[0]]
    assert len(set(page1) & set(page2)) == 0, "a title appeared on two pages"
    assert page1 + page2 == first_pass[:4]
    # The tied block must come back in id order, not insertion order.
    tied = [t for t in first_pass if 9000 <= t <= 9003]
    assert tied == [9000, 9001, 9002, 9003], tied


def test_the_canon_endpoint_serves_the_tab(client, monkeypatch):
    """The read surface behind the Canon tab, including its coverage line.

    The coverage figure ships with its unresolved remainder because the canon is
    matched to the library a few hundred titles per scan — a bare "N of 10,000"
    would read as complete while most of the list had never been looked up.
    """
    monkeypatch.setattr(canon_entries, "load_file", lambda: _FILE)
    c, factory = client

    with factory() as session:
        canon_entries.seed(session)
        entries = list(session.scalars(select(CanonEntry).order_by(CanonEntry.tier)))
        canon_entries.apply_resolution(session, {entries[0].id: 4001, entries[1].id: 4002})
        session.add(Movie(tmdb_id=4001, title="Owned Canon", in_plex=True))
        session.commit()

    body = c.get("/api/musthave/canon").json()
    assert [i["tmdb_id"] for i in body["items"]] == [4002], body
    assert body["coverage"]["owned"] == 1
    assert body["coverage"]["unresolved"] == 3

    tiered = c.get("/api/musthave/canon?tier=4").json()
    assert tiered["items"] == []


def test_the_canon_endpoint_needs_a_session(client):
    """Every read surface is gated once an account exists.

    Asserted against a configured account, because with no account at all the API
    is open by design — the setup wizard has to reach it. A test that accepted
    either answer would pass whatever the code did, which is worse than no test.
    """
    from sift.db.models import Setting

    c, factory = client
    with factory() as session:
        session.merge(Setting(key="auth", value={"username": "x", "password_hash": "y"}))
        session.commit()
    assert c.get("/api/musthave/canon").status_code == 401


def _resolved_canon(factory, count: int) -> None:
    """`count` unowned canon films, all resolved and ready to request."""
    with factory() as session:
        for n in range(count):
            session.add(
                CanonEntry(
                    imdb_id=f"tt700{n:04d}", title=f"Canon {n}", year=1980 + n,
                    tier=1, sources=["award"], votes=10_000 - n, tmdb_id=7000 + n,
                    review_status="resolved",
                )
            )
        session.commit()


def test_the_batch_request_is_capped(client, factory):
    """The whole safety story of this endpoint is the count.

    Tier 1 alone is over four thousand entries and ten thousand films is fifty to
    eighty terabytes, so a batch button without a ceiling is a disk incident one
    click away. Asking for a thousand must not get a thousand.
    """
    from sift.api.routes_musthave import MAX_BATCH_REQUEST

    c, _ = client
    _resolved_canon(factory, MAX_BATCH_REQUEST + 25)

    body = c.post("/api/musthave/canon/request", json={"tier": 1, "limit": 1000}).json()
    assert body["requested"] <= MAX_BATCH_REQUEST
    assert body["remaining"] > 0, "the remainder must be reported, not silently dropped"


def test_the_batch_takes_the_strongest_claims_first(client, factory):
    """Bounded means a choice is being made about which titles get in. It should
    be the same choice the list itself displays — strongest claim, then fame."""
    from sift.db.models import Action

    c, factory_ = client
    _resolved_canon(factory_, 5)

    c.post("/api/musthave/canon/request", json={"tier": 1, "limit": 2})
    with factory_() as session:
        ids = [a.movie_tmdb_id for a in session.scalars(select(Action))]
    # Votes descend with n, so the first two entries are the most famous.
    assert sorted(ids) == [7000, 7001], ids


def test_a_staged_instance_requests_nothing(client, factory, settings):
    """NEGATIVE CONTROL. The dry-run floor is server-authoritative everywhere
    else; a batch endpoint that quietly bypassed it would be the one place a
    staged instance spends real disk."""
    from sift.db.models import Action, ActionStatus

    c, factory_ = client
    _resolved_canon(factory_, 3)
    assert settings.actions.dry_run is True  # the default, and the point

    body = c.post("/api/musthave/canon/request", json={"tier": 1, "limit": 3}).json()
    assert body["dry_run"] is True
    with factory_() as session:
        actions = list(session.scalars(select(Action)))
    assert actions, "the intent is still recorded — staged is audited, not ignored"
    assert all(a.dry_run for a in actions)
    assert all(a.status != ActionStatus.FAILED for a in actions)


def test_an_empty_canon_is_not_an_error(client, factory):
    """Nothing resolved yet is the normal state for the first few scans."""
    c, _ = client
    body = c.post("/api/musthave/canon/request", json={"tier": 1, "limit": 5}).json()
    assert body == {"requested": 0, "failed": 0, "remaining": 0, "dry_run": True}
