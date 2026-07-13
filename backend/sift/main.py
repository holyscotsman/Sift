"""FastAPI application factory + static UI serving.

``create_app`` builds everything from a :class:`~sift.config.Settings` and wires the
shared state (session factory, action engine, scan hub). Tests inject their own
settings / session factory; the CLI uses process settings.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .actions.engine import ActionEngine
from .actions.radarr_writes import RadarrWriter
from .api import routes_actions, routes_health, routes_movies, routes_scan, ws
from .api.deps import AppState
from .config import Settings, get_settings
from .db.session import init_db, make_engine, make_session_factory

log = logging.getLogger("sift")

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("Sift %s starting", __version__)
    app.state.scan_tasks = set()
    yield
    for task in list(app.state.scan_tasks):
        task.cancel()


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    action_engine: ActionEngine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        engine = make_engine(settings.database.path)
        init_db(engine)
        session_factory = make_session_factory(engine)
    if action_engine is None:
        # Phase 0 writer has no live client: proposals/approvals are DB-only and the
        # execution path (Phase 3) is the only thing that ever needs a real client.
        action_engine = ActionEngine(session_factory, RadarrWriter(None))

    app = FastAPI(title="Sift", version=__version__, lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.sift = AppState(
        settings=settings,
        session_factory=session_factory,
        engine=action_engine,
        hub=ws.ScanHub(),
    )
    # scan_tasks also set in lifespan; initialise here so TestClient (which may not
    # run lifespan in every path) always has it.
    app.state.scan_tasks = set()

    for module in (routes_health, routes_scan, routes_movies, routes_actions):
        app.include_router(module.router)
    app.include_router(ws.router)

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"name": "sift", "version": __version__}

    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="ui")
    else:

        @app.get("/")
        def root() -> dict[str, str]:
            return {
                "name": "sift",
                "version": __version__,
                "ui": "not built — run the frontend build, or use /api/*",
            }

    return app
