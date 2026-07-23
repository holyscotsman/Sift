"""Downloads: CSV export of the movie list + the decisions backup.

The CSV shares the exact filters/sort of ``/api/movies`` (the statement builder
is shared), so the download always matches the visible set, streamed row-by-row
and capped at 20k rows. The decisions backup captures the owner's accumulated
judgment — keep-overrides, dismissed must-haves, tuned thresholds — the state
that dies with an ephemeral disk.

Browser downloads can't set auth headers, so like the poster route these accept
the session token as a ``?token=`` query parameter as well.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .. import __version__
from ..db.models import Movie, MustHaveSuggestion
from ..services import settings_store
from .deps import get_session_factory, get_state, presented_token, token_accepted
from .routes_movies import build_movie_stmt

router = APIRouter(prefix="/api", tags=["movies"])

_MAX_ROWS = 20_000
_HEADER = (
    "title",
    "year",
    "library_section",
    "quality",
    "file_size_gb",
    "in_plex",
    "monitored",
    "cutoff_unmet",
)


@router.get("/movies.csv")
def export_movies_csv(
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    token: str | None = None,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
    q: str | None = None,
    section: str | None = None,
    is_kids: bool | None = None,
    monitored: bool | None = None,
    in_plex: bool | None = None,
    has_file: bool | None = None,
    cutoff_unmet: bool | None = None,
    starts_with: str | None = None,
    sort: str = "title",
    order: str = "asc",
) -> StreamingResponse:
    presented = token or presented_token(authorization, x_sift_token)
    if not token_accepted(get_state(request), presented):
        raise HTTPException(status_code=401, detail="login required")

    stmt = build_movie_stmt(
        q=q,
        section=section,
        is_kids=is_kids,
        monitored=monitored,
        in_plex=in_plex,
        has_file=has_file,
        cutoff_unmet=cutoff_unmet,
        starts_with=starts_with,
        sort=sort,
        order=order,
    ).limit(_MAX_ROWS)

    def rows() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_HEADER)
        yield buf.getvalue()
        with factory() as session:
            for m in session.scalars(stmt):
                buf.seek(0)
                buf.truncate()
                writer.writerow(
                    [
                        m.title,
                        m.year if m.year is not None else "",
                        m.library_section or "",
                        m.quality or "",
                        f"{m.file_size / 1e9:.2f}" if m.file_size else "",
                        "yes" if m.in_plex else "no",
                        "yes" if m.monitored else "no",
                        "yes" if m.cutoff_unmet else "no",
                    ]
                )
                yield buf.getvalue()

    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sift-library.csv"'},
    )


@router.get("/export/decisions.json")
def export_decisions(
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    token: str | None = None,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> JSONResponse:
    """The owner's judgment, portable: keep-overrides, dismissed must-haves, and
    tuned thresholds (titles included so the file reads as a document, not just
    ids). Export only — restoring is a write surface that gets its own review."""
    presented = token or presented_token(authorization, x_sift_token)
    if not token_accepted(get_state(request), presented):
        raise HTTPException(status_code=401, detail="login required")

    state = get_state(request)
    with factory() as session:
        kept = [
            {"tmdb_id": int(tid), "title": title}
            for tid, title in session.execute(
                select(Movie.tmdb_id, Movie.title)
                .where(Movie.keep_override.is_(True))
                .order_by(Movie.title.asc())
            )
        ]
        dismissed = [
            {"tmdb_id": int(tid), "title": title}
            for tid, title in session.execute(
                select(MustHaveSuggestion.tmdb_id, MustHaveSuggestion.title)
                .where(MustHaveSuggestion.status == "dismissed")
                .order_by(MustHaveSuggestion.title.asc())
            )
        ]
        thresholds = settings_store.effective_junk(session, state.settings).model_dump()

    payload: dict[str, Any] = {
        "sift_version": __version__,
        "keep_overrides": kept,
        "dismissed_musthaves": dismissed,
        "thresholds": thresholds,
    }
    return JSONResponse(
        payload,
        headers={"Content-Disposition": 'attachment; filename="sift-decisions.json"'},
    )
