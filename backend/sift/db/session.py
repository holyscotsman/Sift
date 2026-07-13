"""Engine and session helpers for the SQLite snapshot.

The snapshot DB is deliberately synchronous SQLAlchemy: SQLite is local and fast,
and keeping it sync avoids an async driver dependency. Network I/O (the slow part)
is async ``httpx`` in ``clients/``; DB writes during a scan are marshalled onto a
worker thread by the caller so they never block the event loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """Create an engine for a SQLite file (or ``:memory:``) with sane pragmas."""
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{Path(db_path)}"
    engine = create_engine(
        url,
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        # WAL improves read/write concurrency during a scan; skip for in-memory.
        if url != "sqlite://":
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


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
