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

**Three things are subtracted**, not one: what you own, what you have already
asked for, and what you have said no to. The last two are what make this a queue
you can work rather than a list that keeps handing back the same titles. A
refusal is permanent by design — see ``IgnoredTitle`` — and a request is
subtracted only once it has actually left Sift, so a staged add correctly leaves
the title here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..db.models import Action, ActionStatus, ActionType, CanonEntry, IgnoredTitle, Movie


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


def _owned() -> ColumnElement[bool]:
    return (
        select(Movie.tmdb_id)
        .where(Movie.in_plex.is_(True), Movie.tmdb_id == CanonEntry.tmdb_id)
        .exists()
    )


def _requested() -> ColumnElement[bool]:
    """An ``add`` that actually left Sift: executed, and not a dry run.

    Radarr's own monitored state is deliberately not consulted. A staged add
    reached nothing, so the title is still genuinely missing and stays on the
    list; an executed one is on its way and would otherwise sit here looking
    un-actioned for however long the download takes.
    """
    return (
        select(Action.movie_tmdb_id)
        .where(
            Action.type == ActionType.ADD,
            Action.status == ActionStatus.EXECUTED,
            Action.dry_run.is_(False),
            Action.movie_tmdb_id == CanonEntry.tmdb_id,
        )
        .exists()
    )


def _ignored() -> ColumnElement[bool]:
    return select(IgnoredTitle.tmdb_id).where(IgnoredTitle.tmdb_id == CanonEntry.tmdb_id).exists()


def missing(
    session: Session, *, tier: int | None = None, limit: int = 200, offset: int = 0
) -> tuple[list[CanonMissing], int]:
    """Unowned, unrequested, un-refused canon — strongest claim first.

    Returns ``(page, total)``.

    Ranked ``(tier, -votes, tmdb_id)``: the canon's own judgement leads, fame
    breaks ties within a tier, and the id makes the order total so the same query
    returns the same page twice. Without that last term two equally famous titles
    swap places between requests and paging silently skips one.

    Source count is *not* in the ranking, and that is a measurement rather than an
    oversight: 24,417 of the 25,000 shipped entries carry exactly one source, so
    ranking by it would be a near-universal tie broken by whatever came next.
    Tier already encodes the same judgement with usable resolution.
    """
    conditions: list[ColumnElement[bool]] = [
        CanonEntry.tmdb_id.is_not(None),
        ~_owned(),
        ~_requested(),
        ~_ignored(),
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


def hidden(session: Session) -> dict[str, int]:
    """How many unowned titles the two subtractions above are holding back.

    Surfaced so that a list which suddenly got shorter can say why. A queue that
    silently drops the thing you just acted on looks broken even when it is
    working exactly as intended.

    One statement, not two: the counts differ only in their predicate, and a
    round trip on hosted Postgres costs more than the ``CASE`` does.
    """
    unowned = [CanonEntry.tmdb_id.is_not(None), ~_owned()]
    row = session.execute(
        select(
            func.coalesce(func.sum(case((_requested(), 1), else_=0)), 0),
            func.coalesce(func.sum(case((_ignored(), 1), else_=0)), 0),
        )
        .select_from(CanonEntry)
        .where(*unowned)
    ).one()
    return {"requested": int(row[0] or 0), "ignored": int(row[1] or 0)}
