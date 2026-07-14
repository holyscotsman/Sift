"""Movie list + detail endpoints (read from the snapshot)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import scoring
from ..db.models import Movie
from .deps import AuthDep, get_session_factory
from .schemas import (
    MovieDetail,
    MovieListResponse,
    MovieOut,
    RatingOut,
    SiftScoreOut,
    WatchOut,
)

router = APIRouter(prefix="/api", tags=["movies"], dependencies=[AuthDep])

_SORTABLE = {
    "title": Movie.title,
    "year": Movie.year,
    "added_at": Movie.added_at,
    "file_size": Movie.file_size,
}


@router.get("/movies", response_model=MovieListResponse)
def list_movies(
    factory: sessionmaker[Session] = Depends(get_session_factory),
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> MovieListResponse:
    stmt = select(Movie)
    if q:
        stmt = stmt.where(Movie.title.ilike(f"%{q}%"))
    if starts_with:
        # A–Z rail jump. A single letter matches titles beginning with it; "#"
        # matches everything that doesn't start with a letter (digits/symbols).
        # Raw first character so the rail agrees with the by-title sort order.
        first = func.upper(func.substr(Movie.title, 1, 1))
        if starts_with == "#":
            stmt = stmt.where((first < "A") | (first > "Z"))
        else:
            stmt = stmt.where(first == starts_with[0].upper())
    if section is not None:
        stmt = stmt.where(Movie.library_section == section)
    if is_kids is not None:
        stmt = stmt.where(Movie.is_kids.is_(is_kids))
    if monitored is not None:
        stmt = stmt.where(Movie.monitored.is_(monitored))
    if in_plex is not None:
        stmt = stmt.where(Movie.in_plex.is_(in_plex))
    if has_file is not None:
        stmt = stmt.where(Movie.has_file.is_(has_file))
    if cutoff_unmet is not None:
        stmt = stmt.where(Movie.cutoff_unmet.is_(cutoff_unmet))

    column = _SORTABLE.get(sort, Movie.title)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

    with factory() as session:
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list(session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
        items = [MovieOut.model_validate(m) for m in rows]
    return MovieListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/movies/{tmdb_id}", response_model=MovieDetail)
def get_movie(
    tmdb_id: int, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> MovieDetail:
    with factory() as session:
        movie = session.get(Movie, tmdb_id)
        if movie is None:
            raise HTTPException(status_code=404, detail="movie not found")
        detail = MovieDetail.model_validate(movie)
        detail.overview = movie.overview
        detail.keywords = list(movie.keywords or [])
        detail.ratings = [
            RatingOut(source=str(r.source), value=r.value, votes=r.votes) for r in movie.ratings
        ]
        detail.watch_history = [
            WatchOut(
                plex_user=w.plex_user,
                plays=w.plays,
                last_played_at=w.last_played_at,
                completion_pct=w.completion_pct,
                is_kids_account=w.is_kids_account,
            )
            for w in movie.watch_history
        ]
        if movie.score is not None:
            payload = movie.score.signals or {}
            band = payload.get("band") or "keep"
            detail.sift_score = SiftScoreOut(
                junk_score=movie.score.junk_score,
                band=band,
                rationale=scoring.rationale(list(payload.get("signals", [])), band),
            )
        return detail
