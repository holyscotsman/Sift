"""Collection completeness — deterministic owned/missing per collection.

Membership is joined from Radarr collections + TMDB; "owned" reflects Plex presence
(set during the scan's finalize step). Only collections you own part of and are
missing part of are interesting.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Collection, CollectionMember

_CHUNK = 500


def collection_gaps(session: Session) -> list[dict[str, Any]]:
    """Collections you own part of and are missing part of.

    Which collections qualify is decided first, from the counts already stored on
    the collection row; only then are members read, and only for those. The
    previous order — every member of every collection, hydrated as an ORM entity
    and sorted, before asking which collections were even interesting — pulled the
    whole membership table across the wire on every load of the page, and most of
    it belonged to collections that are complete (nothing to show) or wholly
    unowned (not yours to complete).

    Members are still read in one pass rather than per collection: a query inside
    the loop is a round trip per collection, free against the SQLite the tests use
    and the dominant cost against the hosted database this runs on.
    """
    wanted = list(
        session.execute(
            select(
                Collection.tmdb_collection_id,
                Collection.name,
                Collection.owned_count,
                Collection.total_count,
            ).where(
                Collection.owned_count > 0,
                Collection.owned_count < Collection.total_count,
            )
        )
    )
    if not wanted:
        return []

    ids = [row[0] for row in wanted]
    by_collection: dict[int, list[tuple[int, str, int | None, bool]]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        for collection_id, tmdb_id, title, year, owned in session.execute(
            select(
                CollectionMember.collection_id,
                CollectionMember.tmdb_id,
                CollectionMember.title,
                CollectionMember.year,
                CollectionMember.owned,
            ).where(CollectionMember.collection_id.in_(chunk))
        ):
            by_collection.setdefault(collection_id, []).append((tmdb_id, title, year, owned))
    for members in by_collection.values():
        # Oldest first, undated last — and by id within a year, so a collection
        # that ties on year does not reorder itself between requests.
        members.sort(key=lambda m: (m[2] is None, m[2] or 0, m[0]))

    gaps: list[dict[str, Any]] = [
        {
            "collection_id": collection_id,
            "name": name,
            "owned_count": owned_count,
            "total_count": total_count,
            "members": [
                {"tmdb_id": tmdb_id, "title": title, "year": year, "owned": owned}
                for tmdb_id, title, year, owned in by_collection.get(collection_id, [])
            ],
        }
        for collection_id, name, owned_count, total_count in wanted
    ]
    gaps.sort(key=lambda g: (g["owned_count"] - g["total_count"], g["collection_id"]))
    return gaps
