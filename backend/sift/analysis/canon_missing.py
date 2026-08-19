"""Canon titles you don't own, ranked by how strongly the canon vouches for them.

The acquisition half of the two-question model. Junk asks whether a file deserves
its disk here; this asks whether a film missing from the shelf is worth getting.
They are not one axis — a bad film can be a keep, a fine film can be junk — and
this module only ever answers the second question.

**Only resolved entries can be compared.** The canon arrives keyed by IMDb id and
the library by TMDB id, so an entry with no ``tmdb_id`` yet is not "missing", it
is *unknown*, and it is excluded rather than guessed at. That is why the coverage
figure reports its unresolved remainder: early on this list is shorter than the
truth, not longer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..db.models import CanonEntry, Movie


@dataclass(frozen=True)
class CanonMissing:
    tmdb_id: int
    imdb_id: str | None
    title: str
    year: int | None
    tier: int
    sources: list[str]
    spine: int | None
    rating: float | None
    votes: int | None


def missing(
    session: Session, *, tier: int | None = None, limit: int = 200, offset: int = 0
) -> tuple[list[CanonMissing], int]:
    """Unowned canon, strongest claim first. Returns ``(page, total)``.

    Ranked ``(tier, -votes, tmdb_id)``: the canon's own judgement leads, fame
    breaks ties within a tier, and the id makes the order total so the same query
    returns the same page twice. Without that last term two equally famous titles
    swap places between requests and paging silently skips one.
    """
    owned = select(Movie.tmdb_id).where(Movie.in_plex.is_(True))
    conditions: list[ColumnElement[bool]] = [
        CanonEntry.tmdb_id.is_not(None),
        CanonEntry.tmdb_id.not_in(owned),
    ]
    if tier is not None:
        conditions.append(CanonEntry.tier == tier)

    # Paged in SQL, not in Python. Reading every unowned entry to hand back two
    # hundred of them meant ten thousand rows across the wire for one screen, and
    # the recommendation shelf asks the same question on every scan. The count is
    # a second statement rather than a second read: what the caller needs from the
    # remainder is how big it is, not what is in it.
    total = session.scalar(select(func.count()).select_from(CanonEntry).where(*conditions)) or 0
    page = list(
        session.scalars(
            select(CanonEntry)
            .where(*conditions)
            .order_by(
                CanonEntry.tier.asc(),
                CanonEntry.votes.desc().nulls_last(),
                CanonEntry.tmdb_id.asc(),
            )
            .limit(max(1, limit))
            .offset(offset)
        )
    )
    return (
        [
            CanonMissing(
                tmdb_id=int(row.tmdb_id or 0),
                imdb_id=row.imdb_id,
                title=row.title,
                year=row.year,
                tier=row.tier,
                sources=list(row.sources or []),
                spine=row.spine,
                rating=row.rating,
                votes=row.votes,
            )
            for row in page
        ],
        total,
    )
