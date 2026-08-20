"""Turn the library into a ranking for the Missing list.

One job: read what is owned, read what the canon knows about films, and write a
score per canon entry. Everything interesting is in ``analysis/affinity.py``,
which is pure arithmetic and testable without a database; this module is the part
that talks to one.

**Recomputed whole, every scan.** Buying two more films by one director changes
the score of every other film that director made, and there is no cheap way to
know which rows those are without reading them all anyway.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from ..analysis import affinity
from ..db.models import CanonAffinity, CanonEntry, CanonMetadata, Movie, utcnow

log = logging.getLogger("sift.canon")

_CHUNK = 500


def build_profile(session: Session) -> affinity.Profile:
    """What the shelf says, in two statements.

    Genres come straight off ``movies`` — TMDB fills them during the scan. There
    is no director column on ``movies`` and adding one is not available on a live
    database, so directors are recovered by joining the owned film's IMDb id to
    the canon's metadata. That covers owned films the canon knows about and no
    others, which is a real limit and the honest one to accept: the alternative
    is a per-title API call for every film in the library.
    """
    owned_genres = [
        list(genres or [])
        for (genres,) in session.execute(select(Movie.genres).where(Movie.in_plex.is_(True)))
    ]
    owned_directors = [
        list(directors or [])
        for (directors,) in session.execute(
            select(CanonMetadata.directors)
            .join(Movie, Movie.imdb_id == CanonMetadata.imdb_id)
            .where(Movie.in_plex.is_(True))
        )
    ]
    return affinity.build_profile(owned_genres, owned_directors)


def recompute(session: Session) -> int:
    """Rewrite every score. Returns how many rows were written.

    Reads the canon and its metadata in one join, scores in Python, writes in
    bulk. Three round trips plus one per five-hundred-row chunk — not one per
    entry, which on twenty-five thousand entries against the hosted database is
    the difference between a scan phase and a stall.
    """
    profile = build_profile(session)

    scored = [
        (
            imdb_id,
            affinity.score(
                profile, tier=tier, genres=list(genres or []), directors=list(directors or [])
            ),
            list(directors or []),
            int(votes or 0),
            affinity.reasons_for(
                profile, tier=tier, genres=list(genres or []), directors=list(directors or [])
            ),
        )
        for imdb_id, tier, votes, genres, directors in session.execute(
            select(
                CanonEntry.imdb_id,
                CanonEntry.tier,
                CanonEntry.votes,
                CanonMetadata.genres,
                CanonMetadata.directors,
            ).outerjoin(CanonMetadata, CanonMetadata.imdb_id == CanonEntry.imdb_id)
            .where(CanonEntry.imdb_id.is_not(None))
        )
        if imdb_id
    ]
    # One director's filmography must not become the whole first page. Applied
    # across every candidate at once, which is why it lives here and not in
    # ``score`` — the toll depends on what else is on the list.
    spread = affinity.spread([(k, s, d, v) for k, s, d, v, _ in scored])
    rows = [
        {
            "imdb_id": imdb_id,
            "score": spread.get(imdb_id, points),
            "reasons": reasons,
            "computed_at": utcnow(),
        }
        for imdb_id, points, _directors, _votes, reasons in scored
    ]

    # Delete-then-insert rather than upsert: the dialects disagree about upsert
    # syntax, the row count is small, and a rewrite cannot leave a stale score
    # behind for an entry that has since been struck from the canon.
    session.execute(delete(CanonAffinity))
    for start in range(0, len(rows), _CHUNK):
        session.execute(insert(CanonAffinity), rows[start : start + _CHUNK])
    session.commit()
    log.info(
        "canon: scored %s entries against a library of %s (%s directors known)",
        len(rows),
        profile.owned,
        len(profile.directors),
    )
    return len(rows)
