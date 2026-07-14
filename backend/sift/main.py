"""FastAPI application factory + static UI serving.

``create_app`` builds everything from a :class:`~sift.config.Settings` and wires the
shared state (session factory, action engine, scan hub). Tests inject their own
settings / session factory; the CLI uses process settings.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .actions.engine import ActionEngine
from .actions.radarr_writes import RadarrWriter
from .ai.registry import build_llm_provider
from .api import (
    routes_actions,
    routes_analysis,
    routes_ask,
    routes_auth,
    routes_health,
    routes_movies,
    routes_posters,
    routes_profile,
    routes_scan,
    routes_settings,
    ws,
)
from .api.deps import AppState
from .config import Settings, get_settings
from .db.session import init_db, make_engine, make_session_factory
from .services.posters import PosterCache

log = logging.getLogger("sift")

# Where the built UI lives. Defaults to the repo layout; overridable via
# SIFT_FRONTEND_DIST so a container (where `sift` is pip-installed elsewhere) can
# point at the copied `dist`.
_FRONTEND_DIST = Path(
    os.environ.get("SIFT_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("Sift %s starting", __version__)
    app.state.scan_tasks = set()
    yield
    for task in list(app.state.scan_tasks):
        task.cancel()
    await app.state.sift.llm.aclose()


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
        # The writer is built from the Radarr connection so an approved delete (or an
        # autonomous add/monitor) can actually be issued. It stays safe by default:
        # every proposal is staged with dry_run unless SIFT_ACTIONS__DRY_RUN=false.
        action_engine = ActionEngine(session_factory, RadarrWriter(settings.radarr))

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
        llm=build_llm_provider(settings),
        posters=PosterCache(settings, session_factory),
    )
    # scan_tasks also set in lifespan; initialise here so TestClient (which may not
    # run lifespan in every path) always has it.
    app.state.scan_tasks = set()

    for module in (
        routes_auth,
        routes_health,
        routes_scan,
        routes_movies,
        routes_posters,
        routes_actions,
        routes_analysis,
        routes_ask,
        routes_settings,
        routes_profile,
    ):
        app.include_router(module.router)
    app.include_router(ws.router)

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"name": "sift", "version": __version__}

    if _FRONTEND_DIST.is_dir():
        # Serve hashed build assets, then fall back to index.html for any other
        # path so client-side (SPA) routes like /library deep-link on refresh.
        assets_dir = _FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        index_file = _FRONTEND_DIST / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "ws/")):
                raise HTTPException(status_code=404, detail="not found")
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file() and candidate.is_relative_to(_FRONTEND_DIST):
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:

        @app.get("/")
        def root() -> dict[str, str]:
            return {
                "name": "sift",
                "version": __version__,
                "ui": "not built — run the frontend build, or use /api/*",
            }

    return app
