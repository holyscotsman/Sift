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


def collection_gaps(session: Session) -> list[dict[str, Any]]:
    """Collections you own part of and are missing part of.

    Members are read in one query and grouped here rather than fetched per
    collection. A query inside the loop is one network round trip per collection —
    free against the SQLite the tests use, and the dominant cost against the hosted
    database this runs on, on every load of the page.
    """
    by_collection: dict[int, list[CollectionMember]] = {}
    for member in session.scalars(select(CollectionMember)):
        by_collection.setdefault(member.collection_id, []).append(member)
    for members in by_collection.values():
        # Oldest first, undated last — and by id within a year, so a collection
        # that ties on year does not reorder itself between requests.
        members.sort(key=lambda m: (m.year is None, m.year or 0, m.tmdb_id))

    gaps: list[dict[str, Any]] = []
    for coll in session.scalars(select(Collection)):
        if coll.owned_count == 0 or coll.owned_count >= coll.total_count:
            continue  # own none, or already complete
        members = by_collection.get(coll.tmdb_collection_id, [])
        gaps.append(
            {
                "collection_id": coll.tmdb_collection_id,
                "name": coll.name,
                "owned_count": coll.owned_count,
                "total_count": coll.total_count,
                "members": [
                    {"tmdb_id": m.tmdb_id, "title": m.title, "year": m.year, "owned": m.owned}
                    for m in members
                ],
            }
        )
    gaps.sort(key=lambda g: (g["owned_count"] - g["total_count"], g["collection_id"]))
    return gaps
