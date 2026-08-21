"""How the engine is built for each database — the settings production depends on.

`_resolve_url` is already pinned in `test_config.py`. What was not pinned is what
`make_engine` does with the URL once it has it, and both branches carry a setting
that fails silently rather than loudly if it goes missing.
"""

from __future__ import annotations

from sqlalchemy import text

from sift.db.session import make_engine, make_session_factory


def test_hosted_postgres_gets_pre_ping_and_a_recycle_window():
    """Neon scales connections to zero, and a pooled connection to a database that
    has gone to sleep surfaces as an error on the *next* request rather than the
    one that idled.

    `pool_pre_ping` turns that into a transparent reconnect and `pool_recycle`
    stops a connection being held past the window in the first place. Without them
    the first page load after a quiet period is a 500 — intermittent, unreproducible
    on a warm instance, and exactly the shape of bug that gets blamed on the app.

    Inspected on the engine rather than by connecting: building an engine opens no
    connection, so this needs no Postgres and no driver round trip.
    """
    engine = make_engine("postgresql://u:p@example.neon.tech/db")

    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 300
    # And the URL normalisation is still applied on the way through.
    assert "sslmode=require" in engine.url.render_as_string(hide_password=True)


def test_sqlite_does_not_get_the_postgres_pool_settings():
    """NEGATIVE CONTROL: the two branches are genuinely different.

    SQLite is a local file with no network and no idle timeout, so pre-ping is a
    query per checkout for nothing. A single `create_engine` call carrying both
    sets of options would pass the test above while quietly taxing every local
    session.
    """
    engine = make_engine(":memory:")

    assert engine.pool._pre_ping is False


def test_sqlite_enforces_foreign_keys(tmp_path):
    """SQLite ignores foreign keys unless asked, per connection.

    Every `ON DELETE CASCADE` in the schema depends on this pragma — without it a
    deleted film leaves its scores, copies and media files behind, and the tests
    that rely on the cascade would pass against a database that never cascades.
    """
    engine = make_engine(tmp_path / "fk.db")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_a_file_backed_sqlite_uses_wal_but_an_in_memory_one_does_not(tmp_path):
    """WAL lets a scan write while a page reads. It is meaningless in memory, where
    there is no file to journal to.

    Mutation-checked: the `if url != "sqlite://"` guard is not what delivers the
    second half — SQLite refuses WAL for an in-memory database on its own, so
    removing the guard leaves this green. The guard avoids a pragma that would do
    nothing; the pin is on the journal mode each database actually ends up in.
    """
    on_disk = make_engine(tmp_path / "wal.db")
    with on_disk.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"

    in_memory = make_engine(":memory:")
    with in_memory.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() != "wal"


def test_a_pooled_connection_can_be_reused_on_another_thread(tmp_path):
    """`check_same_thread=False` is what lets the pipeline marshal DB work onto a
    worker thread, which is the whole reason a scan does not block the event loop.

    The connection has to be *opened here and reused there* for this to mean
    anything. A worker thread that opens its own connection never trips SQLite's
    check at all — the first version of this test did exactly that and passed with
    `check_same_thread=True`, proving nothing. Opening one on the main thread and
    returning it to the pool first is what makes the thread boundary real.
    """
    import threading

    engine = make_engine(tmp_path / "threads.db")
    factory = make_session_factory(engine)

    with factory() as session:  # opens a connection and returns it to the pool
        assert session.execute(text("SELECT 1")).scalar() == 1

    result: list[object] = []
    error: list[BaseException] = []

    def work() -> None:
        try:
            with factory() as session:  # checks the *same* connection back out
                result.append(session.execute(text("SELECT 2")).scalar())
        except BaseException as exc:  # noqa: BLE001 - the failure is the point
            error.append(exc)

    t = threading.Thread(target=work)
    t.start()
    t.join()

    assert not error, f"pooled connection refused on another thread: {error}"
    assert result == [2]
