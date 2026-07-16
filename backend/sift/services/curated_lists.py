"""Curated lists: seed, resolve titles→TMDB ids, and query membership.

Content is human-reviewable and ships ``pending``. ``cult_ids`` feeds the junk
"keep if cult" rule; ``missing_from_lists`` powers the Missing screen's "you don't
own these" section. Ids are resolved from TMDB search during a scan — never
hand-coded — so the data can't silently drift onto the wrong film.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.curated_seed import CURATED_SEED
from ..db.models import CuratedListEntry, Movie


def seed_defaults(session: Session) -> int:
    """Insert the bundled starter entries that aren't present yet. Idempotent."""
    existing = {
        (name, title, year)
        for name, title, year in session.execute(
            select(CuratedListEntry.list_name, CuratedListEntry.title, CuratedListEntry.year)
        )
    }
    added = 0
    for list_name, titles in CURATED_SEED.items():
        for title, year in titles:
            if (list_name, title, year) in existing:
                continue
            session.add(
                CuratedListEntry(
                    list_name=list_name, title=title, year=year, review_status="pending"
                )
            )
            added += 1
    session.commit()
    return added


def pending_resolution(session: Session) -> list[tuple[int, str, int | None]]:
    """Entries still missing a TMDB id — (entry_id, title, year)."""
    rows = session.execute(
        select(CuratedListEntry.id, CuratedListEntry.title, CuratedListEntry.year).where(
            CuratedListEntry.tmdb_id.is_(None)
        )
    )
    return [(rid, title, year) for rid, title, year in rows]


def apply_resolution(session: Session, resolved: dict[int, int]) -> int:
    count = 0
    for entry_id, tmdb_id in resolved.items():
        entry = session.get(CuratedListEntry, entry_id)
        if entry is not None:
            entry.tmdb_id = tmdb_id
            count += 1
    session.commit()
    return count


def list_tmdb_ids(session: Session, list_name: str) -> frozenset[int]:
    rows = session.scalars(
        select(CuratedListEntry.tmdb_id).where(
            CuratedListEntry.list_name == list_name, CuratedListEntry.tmdb_id.is_not(None)
        )
    )
    return frozenset(int(r) for r in rows if r is not None)


def cult_ids(session: Session) -> frozenset[int]:
    return list_tmdb_ids(session, "cult")


def missing_from_lists(session: Session) -> dict[str, list[dict[str, Any]]]:
    """Resolved list entries whose title is NOT in the Plex library, grouped by list."""
    owned = {
        tid
        for (tid,) in session.execute(select(Movie.tmdb_id).where(Movie.in_plex.is_(True)))
    }
    out: dict[str, list[dict[str, Any]]] = {}
    rows = session.scalars(
        select(CuratedListEntry).where(CuratedListEntry.tmdb_id.is_not(None))
    )
    for entry in rows:
        if entry.tmdb_id in owned:
            continue
        out.setdefault(entry.list_name, []).append(
            {
                "tmdb_id": entry.tmdb_id,
                "title": entry.title,
                "year": entry.year,
                "review_status": entry.review_status,
            }
        )
    return out
