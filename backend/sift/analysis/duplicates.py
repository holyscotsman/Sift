"""Duplicate copies — the same film held more than once in the Plex library.

The cheapest disk you will ever reclaim, and the only removal decision in Sift
that carries no curation risk: you are not judging whether a film deserves to
stay, you are noticing you have three rips of it and keeping the best one. The
title survives either way, so there is nothing to regret.

Grouping is by TMDB id, never by title string — "The Fly" (1958) and "The Fly"
(1986) are different films, and half a dozen releases share the name "Godzilla".
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Movie, PlexCopy


@dataclass(frozen=True)
class DuplicateCopy:
    rating_key: str
    library_section: str | None


@dataclass(frozen=True)
class DuplicateGroup:
    tmdb_id: int
    title: str
    year: int | None
    copies: list[DuplicateCopy]

    @property
    def surplus(self) -> int:
        """How many could go. Always one fewer than the number held."""
        return max(0, len(self.copies) - 1)


def find(session: Session, *, limit: int = 200) -> tuple[list[DuplicateGroup], int]:
    """Films held more than once, most-duplicated first.

    Returns ``(groups, total_surplus)`` — the second being how many copies could
    be removed in total while still keeping every film.
    """
    counted = (
        select(PlexCopy.movie_tmdb_id, func.count().label("n"))
        .group_by(PlexCopy.movie_tmdb_id)
        .having(func.count() > 1)
        .subquery()
    )
    rows = list(
        session.execute(
            select(counted.c.movie_tmdb_id, counted.c.n)
            .order_by(counted.c.n.desc())
            .limit(limit)
        )
    )
    groups: list[DuplicateGroup] = []
    for tmdb_id, _count in rows:
        movie = session.get(Movie, tmdb_id)
        copies = list(
            session.scalars(select(PlexCopy).where(PlexCopy.movie_tmdb_id == tmdb_id))
        )
        groups.append(
            DuplicateGroup(
                tmdb_id=tmdb_id,
                title=str(
                    (movie.title if movie else None)
                    or (copies[0].title if copies else None)
                    or f"TMDB {tmdb_id}"
                ),
                year=movie.year if movie else None,
                copies=[DuplicateCopy(c.rating_key, c.library_section) for c in copies],
            )
        )
    # Total surplus is over the whole library, not just the returned page.
    total_surplus = (
        session.scalar(
            select(func.coalesce(func.sum(counted.c.n - 1), 0)).select_from(counted)
        )
        or 0
    )
    return groups, int(total_surplus)
