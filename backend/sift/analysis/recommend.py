"""Taste recommendations — TMDB discovery grounded in what you own.

Deterministic on purpose. We pick the strongest-signal titles you already own as
*anchors* (highest external rating, tie-broken by vote count), pull TMDB
``recommendations`` (falling back to ``similar``) for each, and aggregate. A
candidate scores by how many of your anchors surface it, weighted by how strong
each anchor is and how highly TMDB ranked it. Titles you already own are excluded,
and the reason names the real anchors that produced it.

The AI layer never *picks* titles here — TMDB's graph does. That keeps this in line
with the rest of Sift ("deterministic retrieval, AI only phrases") and means a
recommendation can never be a hallucinated film that doesn't exist.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import Movie, Rating, Recommendation

log = logging.getLogger("sift.analysis.recommend")

# How many owned titles seed the discovery graph, and how deep to read each TMDB
# result. Twelve anchors could yield at most 240 raw candidates — and anchors
# overlap heavily, so after de-duplication and removing what you already own the
# distinct pool fell well short of a couple of hundred. Sixty is enough that the
# list is genuinely long, and it costs sixty upstream calls *per scan* rather
# than per page load, which is what makes that affordable.
_ANCHOR_COUNT = 60
_PER_ANCHOR = 20

# How many ranked rows to keep. The queue is meant to be browsed, not just
# skimmed, so it is stored deep and paged in the UI.
STORED_LIMIT = 500


@dataclass(frozen=True)
class Anchor:
    tmdb_id: int
    title: str
    weight: float


@dataclass
class Candidate:
    tmdb_id: int
    title: str
    year: int | None
    vote_average: float
    poster_path: str | None
    genre_ids: tuple[int, ...] = ()
    score: float = 0.0
    # (anchor_title, contribution) — used to explain *why* this was surfaced.
    sources: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Taste:
    """The library's dominant genres/eras + the owner's emphasis sliders. Only ever
    *reorders* candidates (bounded ≤1.5×); with sliders at zero the multiplier is
    exactly 1, reproducing the unweighted ordering."""

    top_genres: frozenset[str]
    top_eras: frozenset[str]
    genre_weight: float
    era_weight: float

    def multiplier(self, cand: Candidate) -> float:
        boost = 0.0
        if self.top_genres and cand.genre_ids:
            from ..data.tmdb_genres import TMDB_GENRES

            names = {TMDB_GENRES.get(g) for g in cand.genre_ids} - {None}
            if names:
                overlap = len(names & self.top_genres) / len(names)
                boost += 0.35 * self.genre_weight * overlap
        if self.top_eras and cand.year:
            if f"{(cand.year // 10) * 10}s" in self.top_eras:
                boost += 0.15 * self.era_weight
        return min(1.5, 1.0 + boost)


def _read_taste(session: Session) -> Taste:
    from . import profile as profile_analysis

    weights = profile_analysis.get_weights(session)
    genre_counts: dict[str, int] = {}
    era_counts: dict[str, int] = {}
    for (genres, year) in session.execute(
        select(Movie.genres, Movie.year).where(Movie.in_plex.is_(True))
    ):
        for g in genres or []:
            genre_counts[g] = genre_counts.get(g, 0) + 1
        if year:
            era = f"{(year // 10) * 10}s"
            era_counts[era] = era_counts.get(era, 0) + 1
    # Name breaks the tie, so an equally common pair of genres always yields
    # the same five — the query behind these counts has no ORDER BY.
    top_genres = sorted(genre_counts, key=lambda g: (-genre_counts[g], g))[:5]
    top_eras = sorted(era_counts, key=lambda e: (-era_counts[e], e))[:3]
    return Taste(
        top_genres=frozenset(top_genres),
        top_eras=frozenset(top_eras),
        genre_weight=float(weights.get("genre", 0.5)),
        era_weight=float(weights.get("era", 0.5)),
    )


def _read_context(session: Session) -> tuple[list[Anchor], set[int]]:
    """Highest-rated owned titles (anchors) + the full owned-id set (to exclude)."""
    owned = {
        tid for (tid,) in session.execute(select(Movie.tmdb_id).where(Movie.in_plex.is_(True)))
    }
    # Best rating per movie, tie-broken by vote count — a title you rate highly is the
    # best proxy for "more like this".
    best = (
        select(
            Rating.movie_id,
            func.max(Rating.value).label("val"),
            func.max(Rating.votes).label("votes"),
        )
        .group_by(Rating.movie_id)
        .subquery()
    )
    rows = session.execute(
        select(Movie.tmdb_id, Movie.title, best.c.val, best.c.votes)
        .join(best, best.c.movie_id == Movie.tmdb_id)
        .where(Movie.in_plex.is_(True))
        .order_by(best.c.val.desc(), best.c.votes.desc().nulls_last())
        .limit(_ANCHOR_COUNT)
    )
    anchors: list[Anchor] = []
    for tmdb_id, title, val, _votes in rows:
        # Ratings are on a 0–10 scale; normalise to a 0.3–1.0 anchor weight so even a
        # modestly-rated seed still contributes, and a great one dominates.
        weight = max(0.3, min(1.0, (float(val) if val is not None else 6.0) / 10.0))
        anchors.append(Anchor(tmdb_id=int(tmdb_id), title=str(title), weight=weight))
    return anchors, owned


def _year_of(item: dict[str, Any]) -> int | None:
    date = item.get("release_date")
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def _reason(sources: list[tuple[str, float]]) -> str:
    top = [name for name, _ in sorted(sources, key=lambda s: (-s[1], s[0]))[:2]]
    if len(top) >= 2:
        return f"Because you own {top[0]} and {top[1]}"
    if top:
        return f"Because you own {top[0]}"
    return "Matches your library"


def rank(candidates: list[Candidate], taste: Taste) -> list[Candidate]:
    """Most-recommended first.

    The lead key is how many of the owner's own films independently surfaced the
    title — that is what "recommended most" means, and it is a far more robust
    signal than the weighted score, which one very strong anchor's top pick can
    dominate on its own. The weighted score (with the Taste Profile's emphasis
    applied) breaks ties, and ``tmdb_id`` breaks those, so the same library
    produces the same order every time rather than reshuffling between visits.
    """
    return sorted(
        candidates,
        key=lambda c: (-len(c.sources), -c.score * taste.multiplier(c), c.tmdb_id),
    )


async def _collect(
    client: TmdbClient, anchors: list[Anchor], owned: set[int]
) -> tuple[dict[int, Candidate], int]:
    """Aggregate candidates and report how many anchor calls actually reached TMDB —
    so a total wipeout (bad key, TMDB down) reads as an error, not "nothing to add"."""
    candidates: dict[int, Candidate] = {}
    reached = 0
    for anchor in anchors:
        try:
            recs = await client.get_recommendations(anchor.tmdb_id)
            if not recs:
                recs = await client.get_similar(anchor.tmdb_id)
        except Exception as exc:  # noqa: BLE001 - one dead anchor shouldn't sink the set
            log.info("tmdb discovery failed for %s: %s", anchor.tmdb_id, exc)
            continue
        reached += 1
        for idx, item in enumerate(recs[:_PER_ANCHOR]):
            rid = item.get("id")
            if not isinstance(rid, int) or rid in owned:
                continue
            # Earlier in TMDB's list = more relevant; decays but never to zero.
            position_weight = max(0.3, 1.0 - 0.03 * idx)
            contribution = anchor.weight * position_weight
            cand = candidates.get(rid)
            if cand is None:
                raw_genres = item.get("genre_ids")
                cand = Candidate(
                    tmdb_id=rid,
                    title=str(item.get("title") or item.get("name") or "Untitled"),
                    year=_year_of(item),
                    vote_average=float(item.get("vote_average") or 0.0),
                    poster_path=item.get("poster_path"),
                    genre_ids=tuple(g for g in raw_genres if isinstance(g, int))
                    if isinstance(raw_genres, list)
                    else (),
                )
                candidates[rid] = cand
            cand.score += contribution
            cand.sources.append((anchor.title, contribution))
    return candidates, reached


async def recommendations(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    limit: int = 24,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Rank candidate titles you don't own, grounded in your highest-rated films."""
    if not settings.tmdb.enabled or settings.tmdb.api_key is None:
        return {
            "items": [],
            "note": "Connect TMDB in Settings › Connections to get taste-based recommendations.",
        }

    anchors, owned = await asyncio.to_thread(_run, session_factory, _read_context)
    if not anchors:
        return {
            "items": [],
            "note": "Run a scan first — recommendations are built from what you already own.",
        }

    client = TmdbClient(settings.tmdb, transport=transport)
    try:
        candidates, reached = await _collect(client, anchors, owned)
    finally:
        await client.aclose()

    # Every anchor call failed — a connection/key fault, not an empty graph. Don't
    # tell the user their library "covers the graph well" when we never reached TMDB.
    if reached == 0:
        return {
            "items": [],
            "note": (
                "Couldn't reach TMDB for recommendations — check the TMDB connection "
                "in Settings › Connections."
            ),
        }

    # The Taste Profile's emphasis sliders reorder (never gate) the ranking:
    # bounded multiplier over the anchor-derived score.
    taste = await asyncio.to_thread(_run, session_factory, _read_taste)
    ranked = rank(list(candidates.values()), taste)[:limit]
    items = [
        {
            "tmdb_id": c.tmdb_id,
            "title": c.title,
            "year": c.year,
            "vote_average": round(c.vote_average, 1),
            "reason": _reason(c.sources),
        }
        for c in ranked
    ]
    note = None if items else "No new titles surfaced — your library already covers the graph well."
    return {"items": items, "note": note}


def _run(session_factory: sessionmaker[Session], fn: Any) -> Any:
    with session_factory() as session:
        return fn(session)


# Rows per statement, matching the ingest writers.
_CHUNK = 500


def _store(session: Session, ranked: list[Candidate], taste: Taste) -> int:
    """Replace the stored queue with this scan's ranking.

    Replaced wholesale rather than merged: a recommendation is a statement about
    the library as it is now, and a title you have since acquired must leave the
    list rather than linger because nothing thought to remove it. The rank is
    stored alongside so the API can page without re-sorting, and so the order the
    owner sees is the order that was computed rather than whatever the database
    returns.
    """
    session.execute(delete(Recommendation))
    rows = [
        {
            "tmdb_id": c.tmdb_id,
            "title": c.title,
            "year": c.year,
            "vote_average": round(c.vote_average, 1),
            "poster_path": c.poster_path,
            "anchor_count": len(c.sources),
            "score": round(c.score * taste.multiplier(c), 4),
            "sources": [name for name, _ in sorted(c.sources, key=lambda s: (-s[1], s[0]))[:3]],
            "rank": position,
        }
        for position, c in enumerate(ranked)
    ]
    for start in range(0, len(rows), _CHUNK):
        session.execute(insert(Recommendation), rows[start : start + _CHUNK])
    session.commit()
    return len(rows)


async def refresh(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Compute the ranked queue and store it. Called once per scan.

    Returns how many were stored; zero when TMDB is not configured or nothing was
    reachable, which leaves the previous list in place rather than blanking the
    screen over a transient fault.
    """
    if not settings.tmdb.enabled or settings.tmdb.api_key is None:
        return 0
    anchors, owned = await asyncio.to_thread(_run, session_factory, _read_context)
    if not anchors:
        return 0
    client = TmdbClient(settings.tmdb, transport=transport)
    try:
        candidates, reached = await _collect(client, anchors, owned)
    finally:
        await client.aclose()
    if reached == 0 or not candidates:
        return 0
    taste = await asyncio.to_thread(_run, session_factory, _read_taste)
    ranked = rank(list(candidates.values()), taste)[:STORED_LIMIT]

    def _write(session: Session) -> int:
        return _store(session, ranked, taste)

    return int(await asyncio.to_thread(_run, session_factory, _write))


def stored(session: Session, *, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
    """The stored queue, in the order it was computed. Returns ``(items, total)``."""
    total = session.scalar(select(func.count()).select_from(Recommendation)) or 0
    rows = session.scalars(
        select(Recommendation).order_by(Recommendation.rank.asc()).limit(limit)
    )
    items = [
        {
            "tmdb_id": r.tmdb_id,
            "title": r.title,
            "year": r.year,
            "vote_average": r.vote_average,
            "reason": _reason_from(list(r.sources), r.anchor_count),
        }
        for r in rows
    ]
    return items, int(total)


def _reason_from(names: list[str], anchor_count: int) -> str:
    if not names:
        return "Matches your library"
    if anchor_count > len(names):
        return f"Because you own {names[0]} and {anchor_count - 1} other titles"
    if len(names) == 1:
        return f"Because you own {names[0]}"
    return "Because you own " + " and ".join(names[:2])
