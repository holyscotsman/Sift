"""A statement budget for every read endpoint the UI actually calls.

Hosted Postgres bills for round trips and for bytes moved. The tests run on
file-backed SQLite where a round trip is effectively free, so an N+1 introduced
here is invisible to every other test in the suite and shows up as "the app got
slow" weeks later, on somebody else's database.

Version 2607.15.1 exists because `session.merge()` per film made the Plex phase
look hung. `test_scan_cost.py` guards the ingest side of that lesson. This guards
the *read* side, which nothing did.

**The budgets are measurements, not aspirations.** Each is the observed count
plus a little headroom, and the headroom is deliberately small: a budget of 50 on
a query that costs 3 catches nothing. Raising one is a decision to be made
knowingly, and the docstring on the constant says what to look at first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update

from sift.db.models import CanonEntry, Movie, Score, Show
from sift.db.session import init_db, make_engine, make_session_factory
from sift.main import create_app
from sift.services import auth, canon_affinity, canon_entries

# path -> (max statements, max kilobytes)
#
# Statements first: that is the number that turns into wall-clock on a hosted
# database. Bytes second, because Neon meters them and because a payload that
# doubles usually means a field got added to a list endpoint without anyone
# noticing it ships sixty times per page.
BUDGETS: dict[str, tuple[int, float]] = {
    "/api/status": (10, 5),
    # Zero, not "small". The health endpoint probes external services and has
    # no business reading the database at all — a budget of 2 here was caught
    # by the control below as proving nothing, which is exactly its job.
    "/api/health": (0, 5),
    "/api/settings": (4, 5),
    "/api/config": (4, 5),
    "/api/activity": (3, 20),
    "/api/profile": (5, 20),
    "/api/movies?page_size=60": (5, 40),
    "/api/junk?limit=200": (5, 90),
    "/api/shows?page_size=60": (7, 40),
    "/api/duplicates?limit=200": (4, 20),
    "/api/upgrades?limit=200": (4, 20),
    "/api/missing/suggestions?limit=60": (5, 30),
    # The continuation of an endless list. This is the one that has to stay
    # cheap: it is paid again on every scroll, and the counts it skips are the
    # expensive half — they walk every matching row while the page reads sixty
    # off an index.
    "/api/missing/suggestions?limit=60&offset=60&with_total=false": (1, 30),
    "/api/missing/collections": (3, 20),
    "/api/missing/ignored": (3, 20),
    "/api/storage/ledger?limit=500": (10, 20),
    "/api/storage/movies?limit=200": (4, 20),
    "/api/storage/tv?limit=200": (6, 20),
    "/api/storage/baselines": (3, 20),
}


@pytest.fixture(scope="module")
def big_library(tmp_path_factory):
    """A library big enough that an N+1 shows up as one.

    Four thousand owned films and three hundred shows against the full shipped
    canon. A fixture of ten rows would let a per-row query pass every budget
    here, which is the failure mode this file exists to catch.
    """
    tmp_path = tmp_path_factory.mktemp("cost")
    engine = make_engine(tmp_path / "cost.db")
    init_db(engine)
    factory = make_session_factory(engine)

    with factory() as session:
        canon_entries.seed(session)
        session.execute(
            update(CanonEntry).values(tmdb_id=CanonEntry.id, review_status="resolved")
        )
        session.commit()
        ids = [row for (row,) in session.execute(select(CanonEntry.id).limit(4000))]
        session.add_all(
            [
                Movie(
                    tmdb_id=i,
                    title=f"Owned {i}",
                    year=2000,
                    in_plex=True,
                    file_size=5_000_000_000,
                    library_section="Films",
                    genres=["Drama"],
                )
                for i in ids
            ]
        )
        session.commit()
        session.add_all(
            [Score(movie_id=i, junk_score=float(i % 100), signals={}) for i in ids[:2000]]
        )
        session.add_all(
            [
                Show(
                    tvdb_id=100_000 + n,
                    title=f"Show {n}",
                    year=2010,
                    library_section="TV",
                    in_plex=True,
                    genres=["Drama"],
                )
                for n in range(300)
            ]
        )
        session.commit()
        canon_affinity.recompute(session)
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

    return engine, factory, token


@pytest.fixture(scope="module")
def measured(big_library):
    """Every endpoint called once, with its statements counted."""
    from sift.config import load_settings

    engine, factory, token = big_library

    app = create_app(load_settings(config_path=None), session_factory=factory)

    counted: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        counted.append(statement)

    results: dict[str, tuple[int, float, int]] = {}
    with TestClient(app) as client:
        client.headers.update({"Authorization": f"Bearer {token}"})
        for path in BUDGETS:
            counted.clear()
            resp = client.get(path)
            results[path] = (len(counted), len(resp.content) / 1000, resp.status_code)

    event.remove(engine, "before_cursor_execute", _count)
    return results


@pytest.mark.parametrize("path", list(BUDGETS))
def test_an_endpoint_stays_inside_its_budget(measured, path):
    max_statements, max_kb = BUDGETS[path]
    statements, kb, status = measured[path]

    assert status == 200, f"{path} returned {status}"
    assert statements <= max_statements, (
        f"{path} issued {statements} statements against a budget of {max_statements}. "
        "On a hosted database each one is a round trip. The usual cause is a loop "
        "that reads per row where a chunked IN or a join would read once — see "
        "`_persist_plex` in ingest/pipeline.py for the shape the writers use."
    )
    assert kb <= max_kb, (
        f"{path} returned {kb:.1f} kB against a budget of {max_kb} kB. Neon meters "
        "bytes moved, and a list endpoint ships every field sixty times a page."
    )


def test_NEGATIVE_CONTROL_the_budgets_are_not_trivially_satisfiable(measured):
    """A budget of fifty on a query that costs three catches nothing.

    Every endpoint must be using a real fraction of what it is allowed, or the
    numbers above are decoration. This is the test that fails when somebody
    "fixes" a budget breach by raising the budget.
    """
    slack = {
        path: (BUDGETS[path][0], statements)
        for path, (statements, _kb, _status) in measured.items()
        # A budget of zero is exempt because it is the tightest possible claim:
        # "this endpoint must not touch the database", which cannot be slack.
        if BUDGETS[path][0] > 0 and statements * 3 < BUDGETS[path][0]
    }
    assert not slack, (
        f"these budgets are more than triple the observed cost and prove nothing: {slack}"
    )


def test_continuing_an_endless_list_is_cheaper_than_starting_one(measured):
    """The property the Missing page's scroll depends on.

    A first page computes three counts the continuation does not, and those
    counts walk every matching row. If continuing ever costs the same as
    starting, the counts have crept back in and every scroll pays for a number
    that only changes when the owner acts.
    """
    first = measured["/api/missing/suggestions?limit=60"][0]
    more = measured["/api/missing/suggestions?limit=60&offset=60&with_total=false"][0]
    assert more < first, f"continuation cost {more}, first page cost {first}"
