"""Deterministic upgrade detector: library titles whose file is below cutoff.

Radarr already decides "this file's quality is below the profile cutoff" and hands
it to us as ``cutoff_unmet`` during ingestion. This module just reads that verdict
for items that are actually in the Plex library (the source of truth) — no scoring,
no AI. Unlike junk, kids items are included: replacing a low-quality file with a
better one is never a removal, so there's no safety reason to guard them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..db.models import Movie


@dataclass(frozen=True)
class UpgradeCandidate:
    tmdb_id: int
    title: str
    year: int | None
    poster_url: str | None
    library_section: str | None
    quality: str | None
    file_size: int | None
    is_kids: bool


def _base_query() -> Select[tuple[Movie]]:
    # Library membership is Plex's call; the cutoff verdict is Radarr's. A title only
    # qualifies when it's in the library AND has a real file below cutoff.
    return select(Movie).where(
        Movie.in_plex.is_(True),
        Movie.has_file.is_(True),
        Movie.cutoff_unmet.is_(True),
    )


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(_base_query().subquery())) or 0


def candidates(session: Session, *, limit: int = 200) -> list[UpgradeCandidate]:
    stmt = (
        _base_query()
        # Biggest files first: the most disk reclaimed / bandwidth spent on a re-grab.
        .order_by(Movie.file_size.desc().nulls_last(), Movie.title.asc())
        .limit(limit)
    )
    return [
        UpgradeCandidate(
            tmdb_id=m.tmdb_id,
            title=m.title,
            year=m.year,
            poster_url=m.poster_url,
            library_section=m.library_section,
            quality=m.quality,
            file_size=m.file_size,
            is_kids=m.is_kids,
        )
        for m in session.scalars(stmt)
    ]
