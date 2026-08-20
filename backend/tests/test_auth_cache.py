"""The cached account row, and the four ways it must never go stale.

Every gated request needs the account row twice — once to ask whether an account
exists, once to verify the token's signature — and that was two round trips on
hosted Postgres, on every poster, every page of an endless list, and every
twenty-second health poll. Nothing in the row changes except when the owner
changes it, so it is cached between writes.

**This is the one place in the codebase where a caching bug is a security bug.**
``change_password`` rotates the signing secret precisely so that other sessions
stop working, and a cache still serving the old secret would leave a suspected
intruder signed in — the exact thing that rotation exists to prevent. So the pins
here are about invalidation, not about speed, and one of them is a source scan
that fails when a *new* writer forgets.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import event

from sift.services import auth, reset

_AUTH_SRC = Path(auth.__file__)


@pytest.fixture(autouse=True)
def clean_cache():
    auth.invalidate_cache()
    yield
    auth.invalidate_cache()


def _settings_reads(engine, fn) -> int:
    n = {"c": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(_conn, _cur, statement, *_a, **_kw):
        if "FROM settings" in statement:
            n["c"] += 1

    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return n["c"]


def test_the_row_is_read_once_and_then_not_again(factory):
    engine = factory.kw["bind"]
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")

    def read_it_ten_times():
        with factory() as session:
            for _ in range(10):
                auth.get_auth(session)

    assert _settings_reads(engine, read_it_ten_times) == 1


def test_NEGATIVE_CONTROL_the_counter_can_see_a_read_at_all(factory):
    """NEGATIVE CONTROL: a listener that never fires would make the test above
    pass with the cache deleted, the cache broken, or the database unplugged."""
    engine = factory.kw["bind"]
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
    auth.invalidate_cache()

    def read_it_twice_across_invalidation():
        with factory() as session:
            auth.get_auth(session)
            auth.invalidate_cache(session)
            auth.get_auth(session)

    assert _settings_reads(engine, read_it_twice_across_invalidation) == 2


def test_changing_the_password_stops_the_old_token_working(factory):
    """The pin this whole file is for.

    Rotation is the point of ``change_password``: tokens live thirty days, and the
    reason anyone changes a password on a reachable instance is that they think
    someone else has one. A cache that kept the old signing secret would leave
    every other session — including the intruder's — working exactly as before.
    """
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        old = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")
        assert auth.token_valid(session, old)

        replacement = auth.change_password(session, "hunter2hunter2", "correcthorse42")
        assert replacement is not None

    with factory() as session:
        assert auth.token_valid(session, old) is False
        assert auth.token_valid(session, replacement) is True


def test_clearing_the_account_reopens_nothing_that_was_cached(factory):
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")
        assert auth.is_configured(session)

    with factory() as session:
        auth.clear_account(session)

    with factory() as session:
        assert auth.is_configured(session) is False
        assert auth.token_valid(session, token) is False


def test_a_factory_reset_does_not_leave_the_old_login_working(factory):
    """The account goes with the settings table, by bulk delete — which the ORM
    never sees. Nothing in ``auth`` would hear about it, so ``wipe_data`` drops
    the cache itself."""
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")
        assert auth.token_valid(session, token)

    reset.wipe_data(factory)

    with factory() as session:
        assert auth.is_configured(session) is False
        assert auth.token_valid(session, token) is False


def test_two_databases_do_not_share_one_cached_account(factory, tmp_path):
    """Keyed by database, not global. The suite builds a fresh SQLite file per
    test in one process, so a single slot would hand one test the previous test's
    account — and it would be wrong in production too if an instance ever
    addressed two databases."""
    from sift.db.session import init_db, make_engine, make_session_factory

    other_engine = make_engine(tmp_path / "other.db")
    init_db(other_engine)
    other = make_session_factory(other_engine)

    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        assert auth.is_configured(session)

    with other() as session:
        assert auth.is_configured(session) is False


def test_a_caller_cannot_rewrite_what_the_next_request_reads(factory):
    """A copy is handed out, not the cached dict. Otherwise one caller mutating
    its own result quietly rewrites the credentials every later request checks
    against."""
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        # The first read is a *miss* — it copies on the way out of the database
        # anyway, so mutating it proves nothing about the cache. Take a second
        # read, which is a hit, and tamper with that one.
        auth.get_auth(session)
        from_cache = auth.get_auth(session)
        assert from_cache is not None
        from_cache["password_hash"] = "tampered"

        again = auth.get_auth(session)
        assert again is not None and again["password_hash"] != "tampered"


# --------------------------------------------------------------- the source scan


def _functions_that_write_the_auth_row() -> set[str]:
    """Every function in ``auth.py`` that stores or deletes the account row.

    A scan rather than a list, because the failure this guards is someone adding
    a fifth writer — and a hand-maintained list is exactly the thing they would
    also forget to update.
    """
    tree = ast.parse(_AUTH_SRC.read_text())
    writers: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in ("merge", "delete") and any(
                isinstance(a, ast.Call)
                and getattr(a.func, "id", None) == "Setting"
                or (isinstance(a, ast.Name) and a.id == "row")
                for a in inner.args
            ):
                writers.add(node.name)
    return writers


def _invalidates(func_name: str) -> bool:
    tree = ast.parse(_AUTH_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    name = getattr(inner.func, "attr", None) or getattr(inner.func, "id", None)
                    if name in ("invalidate_cache", "_store"):
                        return True
    return False


def test_every_writer_of_the_auth_row_drops_the_cache():
    """The build fails when a new writer forgets.

    ``change_password`` used to merge the row directly, bypassing ``_store``. With
    a cache in front of the read that would have made a password change silently
    stop signing other sessions out — a security regression that no existing test
    would have caught, because the old code had no cache to go stale.
    """
    writers = _functions_that_write_the_auth_row()
    assert writers, "the scan found no writers — has the module been restructured?"
    missing = sorted(name for name in writers if not _invalidates(name))
    assert not missing, f"these write the auth row without dropping the cache: {missing}"


def test_NEGATIVE_CONTROL_the_scan_would_notice_a_writer_that_forgot():
    """NEGATIVE CONTROL: prove the scan can fail. A parser that found nothing, or
    an ``_invalidates`` that returned True for everything, would pass the test
    above while catching nothing at all."""
    assert _invalidates("_store") is True
    assert _invalidates("get_auth") is False
    assert "_store" in _functions_that_write_the_auth_row()


def test_the_ttl_is_a_real_backstop_not_a_decorative_constant(factory, monkeypatch):
    """The cache is invalidated explicitly by every writer, so the TTL exists for
    what those writers cannot see: a direct SQL edit, a restore from backup, a
    second worker. Pinned by shrinking it rather than by waiting thirty seconds —
    what matters is that the expiry is consulted at all.
    """
    engine = factory.kw["bind"]
    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")

    monkeypatch.setattr(auth, "_CACHE_TTL_SECONDS", -1.0)

    def read_twice():
        with factory() as session:
            auth.get_auth(session)
            auth.get_auth(session)

    assert _settings_reads(engine, read_twice) == 2


def test_a_row_changed_outside_the_app_is_picked_up_once_the_ttl_passes(factory, monkeypatch):
    """The scenario the TTL is for, end to end. Nothing in ``auth`` can hear a
    ``UPDATE settings`` typed into psql, so the guarantee is bounded staleness
    rather than none — and this is where that bound is written down."""
    from sift.db.models import Setting

    with factory() as session:
        auth.create_account(session, "owner", "hunter2hunter2")
        assert auth.is_configured(session)

    # Straight at the row, the way a restore or a hand-edit would.
    with factory() as session:
        session.merge(Setting(key="auth", value={}))
        session.commit()

    with factory() as session:
        assert auth.is_configured(session) is True, "expected the cache to still be warm"

    monkeypatch.setattr(auth, "_CACHE_TTL_SECONDS", -1.0)
    with factory() as session:
        assert auth.is_configured(session) is False


def test_the_backstop_is_short_enough_to_be_one():
    """The two tests above shrink the TTL to prove the expiry is consulted, which
    means neither of them can see the shipped value — set it to a century and both
    still pass. This is where the number itself is pinned.

    Not circular: the claim is that a finite backstop exists and is short enough
    to matter. Removing it is a different design — explicit invalidation only,
    with no recovery from an out-of-band write — and anyone choosing that should
    have to come here and say so.
    """
    assert 0 < auth._CACHE_TTL_SECONDS <= 60
