"""Engine and session helpers for the SQLite snapshot.

The snapshot DB is deliberately synchronous SQLAlchemy: SQLite is local and fast,
and keeping it sync avoids an async driver dependency. Network I/O (the slow part)
is async ``httpx`` in ``clients/``; DB writes during a scan are marshalled onto a
worker thread by the caller so they never block the event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def _resolve_url(target: str | Path) -> str:
    """Turn a target (SQLite path, ``:memory:``, or a full DB URL) into a SQLAlchemy
    URL. Postgres URLs are normalised: ``postgres://`` → ``postgresql://`` and SSL is
    required by default (Neon and most hosted Postgres need it)."""
    raw = str(target)
    if "://" not in raw:
        return "sqlite://" if raw == ":memory:" else f"sqlite:///{Path(raw)}"
    if raw.startswith("postgres://"):  # some hosts hand out the legacy scheme
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "sslmode=" not in raw:
        raw += ("&" if "?" in raw else "?") + "sslmode=require"
    return raw


def make_engine(target: str | Path, *, echo: bool = False) -> Engine:
    """Create an engine for SQLite (a path or ``:memory:``) or a full DB URL
    (e.g. Postgres/Neon for a persistent hosted deploy)."""
    url = _resolve_url(target)
    if url.startswith("sqlite"):
        engine = create_engine(
            url, echo=echo, future=True, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if url != "sqlite://":  # WAL improves scan concurrency; skip in-memory
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine

    # Hosted Postgres (Neon) scales connections to zero, so pre-ping + recycle keep a
    # stale pooled connection from surfacing as an error on the next request.
    return create_engine(url, echo=echo, future=True, pool_pre_ping=True, pool_recycle=300)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables. Dev/test convenience; production uses Alembic migrations."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional session context: commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def in_thread[T](factory: sessionmaker[Session], fn: Callable[[Session], T]) -> T:
    """Run sync session work on a worker thread (keeps the event loop free).

    The one place the "open a session, call fn, marshal to a thread" pattern lives —
    the AI modules and pipeline all funnel through here rather than growing copies.
    """

    def _run() -> T:
        with factory() as session:
            return fn(session)

    return await asyncio.to_thread(_run)
