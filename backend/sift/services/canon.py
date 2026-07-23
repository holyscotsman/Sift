"""The internal canon — the backend's private list of films worth owning.

Deterministic by construction: TMDB's top-rated chart (the critical canon,
which is also where award winners live), a revenue-sorted discover sweep
(blockbusters — widely received even when critics weren't kind), the curated
lists (cult / IMDb top / criterion, pending human review), and must-have
suggestions that already passed the anti-nonsense gates. AI never inserts a
title here directly.

The canon itself is backend-only. The Missing page shows canon minus the PLEX
library — Radarr is deliberately ignored, so a wanted-but-not-downloaded title
still reads as missing.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import CanonMovie, Movie, MustHaveSuggestion
from . import curated_lists

log = logging.getLogger("sift.canon")

# Bounded sweep: ~300 top-rated + ~200 blockbusters + curated (~100) + gated
# must-haves. Small, predictable number of upstream calls.
_TOP_RATED_PAGES = 15
_BLOCKBUSTER_PAGES = 10
# Gates for the TMDB-sourced paths — canon means broadly seen and broadly rated.
_MIN_VOTES = 500
_MIN_RATING = 7.0
_BLOCKBUSTER_MIN_VOTES = 1000

_CURATED_SOURCE_LABELS = {
    "cult": "cult classic",
    "imdb_top": "IMDb top",
    "criterion": "criterion",
}


def _year_of(item: dict[str, Any]) -> int | None:
    date = item.get("release_date")
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def _accumulate(
    into: dict[int, dict[str, Any]], items: list[dict[str, Any]], source: str, *, min_votes: int,
    min_rating: float | None,
) -> None:
    for item in items:
        tmdb_id = item.get("id")
        if not isinstance(tmdb_id, int):
            continue
        votes = int(item.get("vote_count") or 0)
        rating = float(item.get("vote_average") or 0.0)
        if votes < min_votes:
            continue
        if min_rating is not None and rating < min_rating:
            continue
        if bool(item.get("adult")):
            continue
        entry = into.setdefault(
            tmdb_id,
            {
                "title": str(item.get("title") or item.get("name") or "Untitled"),
                "year": _year_of(item),
                "poster_path": item.get("poster_path"),
                "vote_average": rating,
                "vote_count": votes,
                "sources": set(),
            },
        )
        entry["sources"].add(source)


async def refresh(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    """Rebuild/merge the canon. Upserts only — an owner-visible dismissal story
    isn't needed because the canon is invisible; only the *missing* slice shows."""
    candidates: dict[int, dict[str, Any]] = {}

    if settings.tmdb.enabled and settings.tmdb.api_key is not None:
        client = TmdbClient(settings.tmdb, transport=transport)
        try:
            for page in range(1, _TOP_RATED_PAGES + 1):
                try:
                    _accumulate(
                        candidates,
                        await client.top_rated(page=page),
                        "top rated",
                        min_votes=_MIN_VOTES,
                        min_rating=_MIN_RATING,
                    )
                except Exception as exc:  # noqa: BLE001 - one dead page shouldn't sink the sweep
                    log.info("canon top_rated page %s failed: %s", page, exc)
            for page in range(1, _BLOCKBUSTER_PAGES + 1):
                try:
                    _accumulate(
                        candidates,
                        await client.discover(
                            page=page,
                            sort_by="revenue.desc",
                            **{"vote_count.gte": _BLOCKBUSTER_MIN_VOTES},
                        ),
                        "blockbuster",
                        min_votes=_BLOCKBUSTER_MIN_VOTES,
                        min_rating=None,  # blockbusters count by reach, not rating
                    )
                except Exception as exc:  # noqa: BLE001
                    log.info("canon discover page %s failed: %s", page, exc)
        finally:
            await client.aclose()

    def _merge(session: Session) -> dict[str, int]:
        # Curated lists (already human-reviewable seeds with resolved tmdb ids).
        for list_name, label in _CURATED_SOURCE_LABELS.items():
            for tmdb_id in curated_lists.list_tmdb_ids(session, list_name):
                entry = candidates.setdefault(tmdb_id, {"sources": set()})
                entry["sources"].add(label)
        # Must-haves that already passed the deterministic gates.
        for row in session.scalars(
            select(MustHaveSuggestion).where(MustHaveSuggestion.status == "suggested")
        ):
            entry = candidates.setdefault(
                row.tmdb_id,
                {
                    "title": row.title,
                    "year": row.year,
                    "vote_average": row.vote_average,
                    "vote_count": row.vote_count,
                    "sources": set(),
                },
            )
            entry["sources"].add("curator pick")

        written = 0
        for tmdb_id, entry in candidates.items():
            canon_row = session.get(CanonMovie, tmdb_id)
            sources = entry.get("sources") or set()
            if canon_row is None:
                # Curated-only entries may lack a title (id-only); resolve it from
                # the snapshot when possible, else skip — canon rows must be named.
                title = entry.get("title")
                if not title:
                    movie = session.get(Movie, tmdb_id)
                    if movie is None:
                        continue
                    entry["title"] = movie.title
                    entry.setdefault("year", movie.year)
                canon_row = CanonMovie(
                    tmdb_id=tmdb_id,
                    title=str(entry["title"]),
                    year=entry.get("year"),
                    poster_path=entry.get("poster_path"),
                    vote_average=entry.get("vote_average"),
                    vote_count=entry.get("vote_count"),
                    sources=sorted(sources),
                )
                session.add(canon_row)
            else:
                canon_row.sources = sorted(set(canon_row.sources or []) | sources)
                if entry.get("vote_average") is not None:
                    canon_row.vote_average = entry["vote_average"]
                if entry.get("vote_count") is not None:
                    canon_row.vote_count = entry["vote_count"]
                if entry.get("poster_path"):
                    canon_row.poster_path = entry["poster_path"]
            written += 1
        session.commit()
        return {"written": written}

    import asyncio

    return await asyncio.to_thread(_run, session_factory, _merge)


def missing(session: Session, *, limit: int = 500) -> tuple[list[CanonMovie], int]:
    """Canon titles NOT in the Plex library (Radarr is ignored on purpose)."""
    in_plex = select(Movie.tmdb_id).where(
        Movie.in_plex.is_(True), Movie.tmdb_id == CanonMovie.tmdb_id
    )
    stmt = (
        select(CanonMovie)
        .where(~in_plex.exists())
        .order_by(
            CanonMovie.vote_count.desc().nulls_last(),
            CanonMovie.title.asc(),
        )
    )
    rows = list(session.scalars(stmt.limit(limit)))
    from sqlalchemy import func

    total = (
        session.scalar(
            select(func.count()).select_from(CanonMovie).where(~in_plex.exists())
        )
        or 0
    )
    return rows, total


def _run(session_factory: sessionmaker[Session], fn: Any) -> Any:
    with session_factory() as session:
        return fn(session)
