"""Shared test fixtures: in-memory DB, settings, and an httpx mock transport."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from sift.config import Settings, load_settings
from sift.db.session import init_db, make_engine, make_session_factory


@pytest.fixture
def factory(tmp_path) -> sessionmaker[Session]:
    engine = make_engine(tmp_path / "test.db")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def settings(monkeypatch) -> Settings:
    # Isolate from any real environment / .env by loading defaults only.
    monkeypatch.delenv("SIFT_CONFIG", raising=False)
    return load_settings(config_path=None)


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def noop_sleep() -> Callable[[float], object]:
    return _noop_sleep


def mock_transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    """Build an httpx MockTransport from a request→response handler."""
    return httpx.MockTransport(handler)
