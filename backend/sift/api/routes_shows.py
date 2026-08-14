"""The TV library: what you have, how big it is, and what quality it is in.

The film list answers "should this be here". This one deliberately does not.
Shows are never scored for removal — a series is forty hours of your life rather
than two, so the question of whether it *deserves* the space is one Sift is not
asked to have an opinion about. What it can say is what you hold, what it costs,
and where the quality is inconsistent with itself.

Size is summarised per show from the episode files, so the figure shown is the
disk actually in use rather than what Sonarr believes it imported.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import tv_recommend, tv_size
from ..db.models import Episode, MediaFile, Season, Show
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import (
    ShowListResponse,
    ShowOut,
    ShowSuggestionOut,
    ShowSuggestionsResponse,
)

router = APIRouter(prefix="/api", tags=["shows"], dependencies=[AuthDep])

_SORTS = {
    "title": Show.title,
    "year": Show.year,
    "last_played_at": Show.last_played_at,
    "plays": Show.plays,
}


@router.get("/shows", response_model=ShowListResponse)
def list_shows(
    factory: sessionmaker[Session] = Depends(get_session_factory),
    q: str | None = None,
    section: str | None = None,
    is_kids: bool | None = None,
    monitored: bool | None = None,
    in_plex: bool | None = None,
    sort: str = "title",
    order: str = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> ShowListResponse:
    stmt = select(Show)
    if q:
        stmt = stmt.where(Show.title.ilike(f"%{q}%"))
    if section:
        stmt = stmt.where(Show.library_section == section)
    if is_kids is not None:
        stmt = stmt.where(Show.is_kids.is_(is_kids))
    if monitored is not None:
        stmt = stmt.where(Show.monitored.is_(monitored))
    if in_plex is not None:
        stmt = stmt.where(Show.in_plex.is_(in_plex))

    column = _SORTS.get(sort, Show.title)
    stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

    with factory() as session:
        # The page first, then aggregates for only the shows on it. Both grouped
        # queries below join media_file to episode to season, so unscoped they scan
        # the whole TV library — on every page of an infinite scroll, twice. The
        # page is at most `page_size` shows; the library is tens of thousands of
        # episodes.
        total = 0
        library_size = 0
        if page == 1:
            total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            # The library-wide figure, needed once for the summary line rather than
            # recomputed per page. A plain SUM, with no grouping to throw away.
            library_size = int(
                session.scalar(
                    select(func.sum(MediaFile.size)).where(MediaFile.episode_id.is_not(None))
                )
                or 0
            )
        rows = list(session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
        page_ids = [show.tvdb_id for show in rows]

        totals: dict[int, tuple[int, int, int]] = {}
        counted: dict[int, dict[str, int]] = {}
        for start in range(0, len(page_ids), 500):
            chunk = page_ids[start : start + 500]
            for tvdb_id, size, episodes, seasons in session.execute(
                select(
                    Season.show_id,
                    func.sum(MediaFile.size),
                    func.count(func.distinct(Episode.id)),
                    func.count(func.distinct(Season.id)),
                )
                .join(Episode, Episode.season_id == Season.id)
                .join(MediaFile, MediaFile.episode_id == Episode.id)
                .where(Season.show_id.in_(chunk))
                .group_by(Season.show_id)
            ):
                totals[tvdb_id] = (int(size or 0), int(episodes or 0), int(seasons or 0))

            for tvdb_id, value, count in session.execute(
                select(Season.show_id, MediaFile.resolution, func.count())
                .join(Episode, Episode.season_id == Season.id)
                .join(MediaFile, MediaFile.episode_id == Episode.id)
                .where(MediaFile.resolution.is_not(None), Season.show_id.in_(chunk))
                .group_by(Season.show_id, MediaFile.resolution)
            ):
                counted.setdefault(tvdb_id, {})[value] = int(count)

        # The resolution most of the show is in. This was previously built by a
        # dict comprehension over rows ordered by count descending — which keeps
        # the *last* row written, so every show displayed its **rarest**
        # resolution. A show that is 95% 1080p with one stray 480p episode showed
        # as 480p. Ties break toward the lower rung, as everywhere else: it is the
        # reading that never overstates what a library is held in.
        resolutions = {
            tvdb_id: max(
                counts, key=lambda r: (counts[r], -tv_size.resolution_rank(r))
            )
            for tvdb_id, counts in counted.items()
        }

    items = [
        ShowOut(
            tvdb_id=show.tvdb_id,
            tmdb_id=show.tmdb_id,
            title=show.title,
            year=show.year,
            status=show.status,
            network=show.network,
            genres=list(show.genres or []),
            library_section=show.library_section,
            is_kids=show.is_kids,
            monitored=show.monitored,
            in_plex=show.in_plex,
            runtime=show.runtime,
            season_count=totals.get(show.tvdb_id, (0, 0, 0))[2],
            episode_count=totals.get(show.tvdb_id, (0, 0, 0))[1],
            total_size=totals.get(show.tvdb_id, (0, 0, 0))[0],
            resolution=resolutions.get(show.tvdb_id),
            plays=show.plays,
            last_played_at=show.last_played_at,
            mean_completion=show.mean_completion,
        )
        for show in rows
    ]
    return ShowListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_size=library_size,
    )


@router.get("/shows/sections", response_model=list[str])
def list_show_sections(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> list[str]:
    with factory() as session:
        rows = session.scalars(
            select(Show.library_section)
            .where(Show.library_section.is_not(None))
            .distinct()
            .order_by(Show.library_section)
        )
        return [r for r in rows if r]


@router.get("/shows/suggestions", response_model=ShowSuggestionsResponse)
async def show_suggestions(
    request: Request,
    limit: int = Query(default=tv_recommend.DEFAULT_LIMIT, ge=1, le=24),
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ShowSuggestionsResponse:
    """A handful of shows you might want next.

    Short on purpose. Twenty-four film suggestions is a browse; twenty-four show
    suggestions is a second job, and a list nobody finishes reading is worse than
    one half its length. The ceiling is 24 rather than unbounded for the same
    reason.

    Seeded by shows you actually finished rather than shows you rate highly: a TV
    library is full of series acquired and never started, and seeding from those
    sends the whole list somewhere you have already declined to go.
    """
    settings = get_settings(request)
    items = await tv_recommend.suggest(factory, settings, limit=limit)
    detail = ""
    if not items:
        with factory() as session:
            seeds, _owned = tv_recommend.anchors(session)
        if not settings.tmdb.enabled or not settings.tmdb.api_key:
            detail = "Connect TMDB in Settings to get suggestions."
        elif not seeds:
            detail = (
                "Nothing to go on yet — suggestions come from shows you have actually "
                "watched through, so this fills in once Tautulli has some history."
            )
        else:
            detail = "Nothing new worth suggesting right now."
    return ShowSuggestionsResponse(
        items=[
            ShowSuggestionOut(
                tmdb_id=s.tmdb_id,
                title=s.title,
                year=s.year,
                overview=s.overview,
                poster_path=s.poster_path,
                vote_average=s.vote_average,
                vote_count=s.vote_count,
                because_of=list(s.because_of),
            )
            for s in items
        ],
        detail=detail,
    )
