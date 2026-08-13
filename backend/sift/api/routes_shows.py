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

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Episode, MediaFile, Season, Show
from .deps import AuthDep, get_session_factory
from .schemas import ShowListResponse, ShowOut

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
        # Sizes come from the files themselves, in one grouped query rather than
        # per show — a TV library has an order of magnitude more episodes than a
        # film library has films, and a per-row lookup here is the mistake
        # 2607.15.1 was about.
        totals = {
            tvdb_id: (int(size or 0), int(episodes or 0), int(seasons or 0))
            for tvdb_id, size, episodes, seasons in session.execute(
                select(
                    Season.show_id,
                    func.sum(MediaFile.size),
                    func.count(func.distinct(Episode.id)),
                    func.count(func.distinct(Season.id)),
                )
                .join(Episode, Episode.season_id == Season.id)
                .join(MediaFile, MediaFile.episode_id == Episode.id)
                .group_by(Season.show_id)
            )
        }
        resolutions = {
            tvdb_id: value
            for tvdb_id, value in session.execute(
                select(Season.show_id, MediaFile.resolution)
                .join(Episode, Episode.season_id == Season.id)
                .join(MediaFile, MediaFile.episode_id == Episode.id)
                .where(MediaFile.resolution.is_not(None))
                .group_by(Season.show_id, MediaFile.resolution)
                .order_by(Season.show_id, func.count().desc())
            )
        }

        total = 0
        if page == 1:
            total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list(session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))

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
        total_size=sum(v[0] for v in totals.values()),
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
