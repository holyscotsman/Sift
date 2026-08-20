"""Keeping the Missing list from ever running out.

The shipped canon is twenty-five thousand films, which is a long way from
endless but is not infinite either, and a library that works through it deserves
a list that keeps going. Two more sources extend it, in the order the owner
asked for: TMDB discovery first, then whichever AI providers are connected.

**Everything lands in the same table.** A top-up writes a ``CanonEntry`` exactly
like the shipped list does, so there is one list, one ranking and one set of
subtractions — not a second surface that has to be reconciled with the first. The
only thing that distinguishes a top-up row is its ``file_version`` and the
reasons it carries.

**It only runs when the list is actually running low** (:data:`LOW_WATER`).
Discovery costs API budget and every candidate is a round trip, so spending that
while twenty thousand titles are still queued would buy nothing.

**Theatrical is enforced at the query, not after it.** TMDB's
``with_release_type=3|2`` means theatrical or limited theatrical, which is the
owner's rule stated as a filter rather than as a judgement: a film that opened in
cinemas is a candidate however badly it did, and a direct-to-video release is
not. ``exclude_list.json`` catches what slips through, and neither of them is an
opinion about quality.

AI is a *source of candidates only*. Every title it names still has to resolve on
TMDB and pass the same deterministic gates as everything else — a film that does
not exist dies at the search, and nothing an AI says is ever taken as fact.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import CanonEntry, IgnoredTitle, Movie, Setting, utcnow
from ..db.session import in_thread
from . import exclusions

log = logging.getLogger("sift.topup")

# Below this many actionable titles the list is close enough to empty to be worth
# spending API budget on. Above it, a top-up would add to a queue nobody has
# reached the bottom of.
LOW_WATER = 500

# Pages fetched per sweep per run. Twenty results a page, so a run adds at most a
# few hundred candidates — enough to matter, small enough that a rate-limited API
# is not hammered by one button press.
PAGES_PER_RUN = 5

# TMDB's discovery cursor lives here so successive runs go deeper into the same
# sweep rather than re-reading page one for ever.
_CURSOR_KEY = "topup_cursor"

# Consensus floor. Low enough to admit a genuine theatrical flop, which the owner
# explicitly wants considered; high enough to exclude things with no audience at
# all. This is a measure of reach, never of quality.
MIN_VOTES = 100

# Features only. Applied as a discovery parameter, so shorts never come back at
# all rather than being fetched and then discarded.
MIN_RUNTIME = 60

# Top-up rows sit below every curated pillar. They are evidence that a film
# exists and played in cinemas, not evidence that anyone considers it essential.
TOPUP_TIER = 4

FILE_VERSION = "topup"

# Each sweep is a different way of being worth watching, so that a library which
# exhausts one does not simply get more of the same.
_SWEEPS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("popular", "widely seen", {"sort_by": "vote_count.desc"}),
    ("acclaimed", "highly rated", {"sort_by": "vote_average.desc", "vote_count.gte": 500}),
    ("revenue", "box office", {"sort_by": "revenue.desc"}),
)


def _cursor(session: Session) -> dict[str, int]:
    row = session.get(Setting, _CURSOR_KEY)
    value = (row.value if row else None) or {}
    return {name: int(value.get(name) or 0) for name, _label, _params in _SWEEPS}


def _save_cursor(session: Session, cursor: dict[str, int]) -> None:
    row = session.get(Setting, _CURSOR_KEY)
    if row is None:
        session.add(Setting(key=_CURSOR_KEY, value=dict(cursor)))
    else:
        row.value = {**(row.value or {}), **cursor}
    session.commit()


def _known(session: Session) -> set[int]:
    """Every TMDB id the list must not offer again.

    Owned, already on the list, or refused. Read as one set of three cheap
    id-only queries rather than checked per candidate: a hundred candidates would
    otherwise be a hundred round trips, which is free here and ruinous on Neon.
    """
    known: set[int] = set()
    known.update(tid for (tid,) in session.execute(select(Movie.tmdb_id)))
    known.update(
        tid
        for (tid,) in session.execute(
            select(CanonEntry.tmdb_id).where(CanonEntry.tmdb_id.is_not(None))
        )
        if tid is not None
    )
    known.update(tid for (tid,) in session.execute(select(IgnoredTitle.tmdb_id)))
    return known


def remaining(session: Session) -> int:
    from ..analysis import canon_missing

    _rows, total = canon_missing.missing(session, limit=1)
    return total


def _gate(row: dict[str, Any], known: set[int]) -> dict[str, Any] | None:
    """Deterministic checks on one discovery result. No AI, no judgement."""
    tmdb_id = row.get("id")
    title = str(row.get("title") or "").strip()
    if not isinstance(tmdb_id, int) or not title or tmdb_id in known:
        return None
    if row.get("adult"):
        return None
    release = str(row.get("release_date") or "")
    if not release or release > datetime.now(UTC).date().isoformat():
        return None  # unreleased: not missing from a library, merely not out yet
    votes = int(row.get("vote_count") or 0)
    if votes < MIN_VOTES:
        return None
    year = int(release[:4]) if release[:4].isdigit() else None
    if exclusions.excluded(title=title, year=year):
        return None
    return {
        "tmdb_id": tmdb_id,
        "title": title,
        "year": year,
        "rating": float(row.get("vote_average") or 0.0) or None,
        "votes": votes or None,
    }


async def _discover(
    client: TmdbClient, cursor: dict[str, int], known: set[int]
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    found: dict[int, dict[str, Any]] = {}
    for name, label, params in _SWEEPS:
        start = cursor[name] + 1
        for page in range(start, start + PAGES_PER_RUN):
            try:
                results = await client.discover(
                    page=page,
                    include_adult=False,
                    **{
                        "with_release_type": "3|2",
                        "with_runtime.gte": MIN_RUNTIME,
                        "vote_count.gte": MIN_VOTES,
                        **params,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - one dead page must not sink the sweep
                log.info("topup %s page %s failed: %s", name, page, exc)
                break
            if not results:
                break
            cursor[name] = page
            for row in results:
                gated = _gate(row, known)
                if gated is None:
                    continue
                entry = found.setdefault(gated["tmdb_id"], {**gated, "sources": []})
                if label not in entry["sources"]:
                    entry["sources"].append(label)
    return found, cursor


async def _from_ai(
    session_factory: sessionmaker[Session],
    settings: Settings,
    client: TmdbClient,
    known: set[int],
    limit: int,
) -> dict[int, dict[str, Any]]:
    """Candidates named by whichever providers are connected, then gated.

    Reuses the must-have machinery rather than growing a second prompt and a
    second parser: the question ("films this library is missing") is the same one,
    and one implementation of "an AI said it, so check it" is easier to keep
    honest than two.

    The exclusion list is applied *after* the shared gates rather than instead of
    them, because an AI is the source most likely to name a direct-to-video sequel
    and call it essential.
    """
    from ..ai.musthave import gated_candidates

    accepted = await gated_candidates(session_factory, settings, client, set(known), limit=limit)
    found: dict[int, dict[str, Any]] = {}
    for row in accepted:
        if exclusions.excluded(title=row["title"], year=row.get("year")):
            continue
        found[row["tmdb_id"]] = {
            "tmdb_id": row["tmdb_id"],
            "title": row["title"],
            "year": row.get("year"),
            "rating": row.get("vote_average"),
            "votes": row.get("vote_count"),
            "sources": ["suggested"],
        }
    log.info("topup: %s AI candidates survived the gates", len(found))
    return found


def _persist(session: Session, found: dict[int, dict[str, Any]]) -> int:
    """Write survivors as canon entries. Re-checks what is known inside the same
    session, because discovery and the write are minutes apart on a slow API and
    a scan may have landed in between."""
    if not found:
        return 0
    known = _known(session)
    rows = [row for tmdb_id, row in found.items() if tmdb_id not in known]
    for row in rows:
        session.add(
            CanonEntry(
                imdb_id=None,
                title=row["title"],
                year=row["year"],
                tier=TOPUP_TIER,
                sources=list(row["sources"]),
                rating=row.get("rating"),
                votes=row.get("votes"),
                tmdb_id=row["tmdb_id"],
                # Already resolved: discovery hands back TMDB ids, so these skip
                # the resolution budget the IMDb-keyed canon has to spend.
                review_status="resolved",
                file_version=FILE_VERSION,
                updated_at=utcnow(),
            )
        )
    session.commit()
    return len(rows)


async def topup(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    force: bool = False,
    ai_limit: int = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Extend the Missing list. Returns what happened, including why not.

    ``force`` skips the low-water check for the case where someone pressed the
    button on purpose. Nothing else about the run changes: the same gates apply,
    and a forced run on a full list will simply find that everything it sees is
    already known.
    """
    if not settings.tmdb.enabled or settings.tmdb.api_key is None:
        return {"added": 0, "remaining": 0, "ran": False, "note": "connect TMDB first"}

    left = await in_thread(session_factory, remaining)
    if not force and left >= LOW_WATER:
        return {"added": 0, "remaining": left, "ran": False, "note": "the list is still deep"}

    known = await in_thread(session_factory, _known)
    cursor = await in_thread(session_factory, _cursor)

    client = TmdbClient(settings.tmdb, transport=transport)
    try:
        found, cursor = await _discover(client, cursor, known)
        ai_found = await _from_ai(session_factory, settings, client, known, ai_limit)
    finally:
        await client.aclose()

    for tmdb_id, row in ai_found.items():
        if tmdb_id in found:
            # Two sources naming the same film is the one case where source count
            # means something, so keep both reasons rather than the first one.
            for reason in row["sources"]:
                if reason not in found[tmdb_id]["sources"]:
                    found[tmdb_id]["sources"].append(reason)
        else:
            found[tmdb_id] = row

    added = await in_thread(session_factory, lambda s: _persist(s, found))
    await in_thread(session_factory, lambda s: _save_cursor(s, cursor))
    left = await in_thread(session_factory, remaining)
    log.info("topup: %s added, %s remaining", added, left)
    return {"added": added, "remaining": left, "ran": True, "considered": len(found)}
