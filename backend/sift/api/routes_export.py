"""CSV export of the movie list.

Same filters and sort as ``/api/movies`` (the statement builder is shared), so
the download always matches the visible set. Streams row-by-row — a 10k-title
library never materialises as one giant string — and is capped at 20k rows.

Browser downloads can't set auth headers, so like the poster route this accepts
the session token as a ``?token=`` query parameter as well.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

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
