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


# Films per database round trip, matching the ingest writers and the scoring loop.
_CHUNK = 500


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
    # Both lookups are read once for the whole page rather than once per group.
    # The per-group shape cost two round trips each, and `find` is called twice on
    # every load of the Storage screen (once directly, once through the ledger)
    # with a limit of a thousand — so a library with a few hundred duplicated
    # films paid for it in the thousands. Free on the SQLite the tests run
    # against, dominant against hosted Postgres: the 2607.15.1 lesson again.
    ids = [int(tmdb_id) for tmdb_id, _count in rows]
    movies: dict[int, Movie] = {}
    copies_by_movie: dict[int, list[PlexCopy]] = {}
    for start in range(0, len(ids), _CHUNK):
        batch = ids[start : start + _CHUNK]
        for found in session.scalars(select(Movie).where(Movie.tmdb_id.in_(batch))):
            movies[found.tmdb_id] = found
        # Ordered so the copies of a film come back the same way every request;
        # the first one names the group when the film itself is unknown.
        for copy in session.scalars(
            select(PlexCopy).where(PlexCopy.movie_tmdb_id.in_(batch)).order_by(PlexCopy.rating_key)
        ):
            copies_by_movie.setdefault(copy.movie_tmdb_id, []).append(copy)

    groups: list[DuplicateGroup] = []
    for tmdb_id in ids:
        movie = movies.get(tmdb_id)
        copies = copies_by_movie.get(tmdb_id, [])
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
