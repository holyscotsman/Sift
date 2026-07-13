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
    gaps: list[dict[str, Any]] = []
    for coll in session.scalars(select(Collection)):
        if coll.owned_count == 0 or coll.owned_count >= coll.total_count:
            continue  # own none, or already complete
        members = session.scalars(
            select(CollectionMember)
            .where(CollectionMember.collection_id == coll.tmdb_collection_id)
            .order_by(CollectionMember.year.asc().nulls_last())
        ).all()
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
    gaps.sort(key=lambda g: g["total_count"] - g["owned_count"], reverse=True)
    return gaps
