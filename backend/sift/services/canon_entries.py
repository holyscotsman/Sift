"""The validated canon: seeding it, resolving it, and measuring coverage.

Ten thousand films worth owning, assembled outside this app from Criterion,
Wikipedia's cult list, award records and an IMDb consensus sweep. The list is a
fact about cinema, not about this household — which is what lets it serve both
questions Sift asks. A canon title you *don't* own is something to acquire; a
canon title you *do* own is something the junk queue should leave alone.

**It arrives keyed by IMDb id and the library is keyed by TMDB id.** Nothing can
be compared until those are reconciled, so resolution is the load-bearing step
here, and it is deliberately spread across scans rather than done at once: ten
thousand lookups against a rate-limited API is not a thing to do while someone
waits for a scan.

Absence from the canon is never evidence of anything. Ten thousand films is not
every good film, so a title being missing from this list says only that the list
does not mention it.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..db.models import CanonEntry, Movie, utcnow
from . import exclusions

log = logging.getLogger("sift.canon")

_DATA = Path(__file__).resolve().parent.parent / "data" / "canon_25k.json"

# Rows written per statement batch, matching the ingest writers.
_CHUNK = 500

# Tiers whose owned titles are protected from the junk queue. Tiers 1-3 are
# curated, award and consensus canon — proposing their deletion would contradict
# the acquisition half of the same app. Tier 4 is fame-fill, and famous but
# unwatched mediocrity is exactly what the junk queue exists to surface.
PROTECTED_TIERS = 3

# Give up on a title after this many failed resolution attempts, so a handful of
# unresolvable entries cannot consume the budget on every scan for ever.
MAX_RESOLVE_ATTEMPTS = 3

# Tests set this to shrink the per-scan resolution budget; zero means "use the
# pipeline's own figure".
CANON_BUDGET_OVERRIDE = 0


@lru_cache(maxsize=1)
def load_file() -> dict[str, Any]:
    """The canon data file, parsed once per process."""
    if not _DATA.exists():  # pragma: no cover - the file ships with the package
        log.warning("canon data file missing at %s", _DATA)
        return {"version": "", "titles": []}
    return dict(json.loads(_DATA.read_text()))


def file_version() -> str:
    return str(load_file().get("version") or "")


def seed(session: Session) -> int:
    """Load the canon into the database, once per file version.

    Idempotent by ``(file_version, imdb_id)``: re-running is a no-op, and a
    refreshed file adds only what it introduces. Rows already carrying a resolved
    ``tmdb_id`` are left exactly as they are — resolution costs API budget spread
    over many scans, and throwing it away to re-import an unchanged title would
    be paying for it twice.
    """
    data = load_file()
    # Hand additions are seeded alongside the file and default to tier 1: the
    # point of writing a title into the overrides file is that the generated list
    # got it wrong, so the generated list does not get to overrule it. Appended
    # in one pass — rebuilding a twenty-five-thousand-item list per override is
    # the sort of quadratic that only shows up once the file has entries in it.
    titles = [
        *(data.get("titles") or []),
        *(
            {**row, "tier": int(row.get("tier") or 1), "sources": ["curated"]}
            for row in exclusions.always_recommend()
        ),
    ]
    if not titles:
        return 0
    version = str(data.get("version") or "")

    known = {
        imdb_id
        for (imdb_id,) in session.execute(
            select(CanonEntry.imdb_id).where(CanonEntry.imdb_id.is_not(None))
        )
    }
    # Entries with no IMDb id are keyed by title and year instead; without this
    # they would be re-added on every seed.
    known_titles = {
        (title, year)
        for title, year in session.execute(
            select(CanonEntry.title, CanonEntry.year).where(CanonEntry.imdb_id.is_(None))
        )
    }

    struck_ids, struck_titles = exclusions.never_recommend_keys()
    fresh: list[dict[str, Any]] = []
    for entry in titles:
        imdb_id = entry.get("imdb_id") or None
        title = entry.get("title")
        year = entry.get("year")
        if not title:
            continue
        if _struck_out(struck_ids, struck_titles, imdb_id, title, year):
            continue
        if imdb_id is not None:
            if imdb_id in known:
                continue
            known.add(imdb_id)
        else:
            if (title, year) in known_titles:
                continue
            known_titles.add((title, year))
        fresh.append(
            {
                "imdb_id": imdb_id,
                "title": title,
                "year": year if isinstance(year, int) else None,
                "tier": int(entry.get("tier") or 4),
                "sources": list(entry.get("sources") or []),
                "spine": entry.get("spine") if isinstance(entry.get("spine"), int) else None,
                "rating": entry.get("rating"),
                "votes": entry.get("votes"),
                "tmdb_id": None,
                "resolve_attempts": 0,
                "review_status": "pending",
                "file_version": version,
                "updated_at": utcnow(),
            }
        )

    # Inserted in bulk, not one ``session.add`` at a time. Ten thousand rows added
    # individually is ten thousand round trips on the first scan against a hosted
    # database — free on SQLite, close to a minute on Neon, and indistinguishable
    # from a stall while it happens. This is the same lesson as 2607.15.1, and
    # seeding the canon is the largest single insert the app performs.
    added = len(fresh)
    for start in range(0, added, _CHUNK):
        session.execute(insert(CanonEntry), fresh[start : start + _CHUNK])
    session.commit()
    prune_struck_out(session)
    if added:
        log.info("canon: seeded %s new entries from %s", added, version or "(no version)")
    return added


def _struck_out(
    ids: set[str],
    titles: set[tuple[str, int]],
    imdb_id: str | None,
    title: str,
    year: Any,
) -> bool:
    """Has the owner written this film into ``never_recommend``?

    **Either key matches, and that is deliberately the opposite of how the
    exclusion list behaves.** There, an IMDb id decides alone, because the list is
    generated, id-keyed and complete over its own domain — an id it does not
    mention is a film it has no opinion about, and a title match would let a
    different film answer for it.

    This file is neither generated nor complete. It is one person writing down a
    decision about a specific film, using whatever they had to hand — and most
    people have a title and a year, not ``tt0000009``. Refusing a title match
    because the stored row happens to carry an id would mean the correction
    silently did nothing, which is the exact failure this whole pass exists to
    prevent. The cost is a same-title-same-year collision, which is rare and
    which the year already narrows to almost nothing.
    """
    if imdb_id and imdb_id in ids:
        return True
    return isinstance(year, int) and (exclusions.normalize(title), year) in titles


def prune_struck_out(session: Session) -> int:
    """Delete canon rows the owner has struck out. Returns how many went.

    Seeding skips them on the way in, but most of the list was already stored
    before the file was ever edited — so without this a hand correction is
    silently inert against the twenty-five thousand titles that shipped, which is
    the half someone is most likely to be looking at when they reach for it.

    Bounded by the size of the overrides file rather than by the canon: the
    strike list is hand-authored and small, so the ids are matched in Python and
    the delete is a single statement over the handful that matched. Doing it the
    other way — pulling twenty-five thousand rows back to compare them — is the
    mistake this codebase keeps a changelog entry about.
    """
    ids, titles = exclusions.never_recommend_keys()
    if not ids and not titles:
        return 0
    conditions: list[Any] = []
    if ids:
        conditions.append(CanonEntry.imdb_id.in_(sorted(ids)))
    doomed: set[int] = set()
    if conditions:
        doomed.update(
            row_id for (row_id,) in session.execute(select(CanonEntry.id).where(*conditions))
        )
    if titles:
        # Normalisation cannot be expressed in SQL portably, so the title strikes
        # are matched by year first — a narrow slice — and normalised in Python.
        years = sorted({year for _t, year in titles})
        for row_id, row_title, row_year in session.execute(
            select(CanonEntry.id, CanonEntry.title, CanonEntry.year).where(
                CanonEntry.year.in_(years)
            )
        ):
            if (exclusions.normalize(row_title), row_year) in titles:
                doomed.add(row_id)
    if not doomed:
        return 0
    session.execute(delete(CanonEntry).where(CanonEntry.id.in_(sorted(doomed))))
    session.commit()
    log.info("canon: removed %s struck-out entries", len(doomed))
    return len(doomed)


def pending_resolution(
    session: Session, limit: int
) -> list[tuple[int, str | None, str, int | None]]:
    """The next entries to resolve — ``(id, imdb_id, title, year)``.

    Ordered by tier so the strongest claims to canon resolve first: if the budget
    only ever covers part of the list, the part it covers should be the part that
    matters most.
    """
    if limit <= 0:
        return []
    rows = session.execute(
        select(CanonEntry.id, CanonEntry.imdb_id, CanonEntry.title, CanonEntry.year)
        .where(
            CanonEntry.tmdb_id.is_(None),
            CanonEntry.review_status == "pending",
            CanonEntry.resolve_attempts < MAX_RESOLVE_ATTEMPTS,
        )
        .order_by(CanonEntry.tier.asc(), CanonEntry.id.asc())
        .limit(limit)
    )
    return [(rid, imdb_id, title, year) for rid, imdb_id, title, year in rows]


def apply_resolution(
    session: Session, resolved: dict[int, int | None]
) -> tuple[int, int]:
    """Record what resolution found. Returns ``(resolved, given_up)``.

    A miss is a counted attempt rather than a failure: TMDB not finding a title
    today does not make it un-canonical, and the entry is tried again next scan
    until the attempt ceiling is reached.
    """
    if not resolved:
        return (0, 0)
    ids = sorted(resolved)
    rows: dict[int, CanonEntry] = {}
    for start in range(0, len(ids), _CHUNK):
        for row in session.scalars(
            select(CanonEntry).where(CanonEntry.id.in_(ids[start : start + _CHUNK]))
        ):
            rows[row.id] = row

    found = 0
    exhausted = 0
    for entry_id, tmdb_id in resolved.items():
        entry = rows.get(entry_id)
        if entry is None:
            continue
        row = entry
        if tmdb_id:
            row.tmdb_id = tmdb_id
            row.review_status = "resolved"
            found += 1
        else:
            row.resolve_attempts += 1
            if row.resolve_attempts >= MAX_RESOLVE_ATTEMPTS:
                row.review_status = "unresolvable"
                exhausted += 1
    session.commit()
    return (found, exhausted)


def protected_tmdb_ids(session: Session) -> set[int]:
    """Owned-title protection: resolved canon in the protected tiers.

    One statement, read as a set and diffed in memory. This feeds the recognition
    floor, so it runs inside the scoring loop's session and must not become a
    per-title lookup.
    """
    return {
        tmdb_id
        for (tmdb_id,) in session.execute(
            select(CanonEntry.tmdb_id).where(
                CanonEntry.tmdb_id.is_not(None),
                CanonEntry.tier <= PROTECTED_TIERS,
            )
        )
    }


def coverage(session: Session) -> dict[str, int]:
    """How much of the canon is on the server, and how much is still unresolved.

    ``owned`` counts only *resolved* entries that match a library title, so it is
    a floor rather than an estimate — early on, the true figure is higher than
    this reports because resolution has not caught up. ``unresolved`` is reported
    alongside precisely so the number is not mistaken for the whole story.
    """
    total = session.scalar(select(func.count()).select_from(CanonEntry)) or 0
    resolved = (
        session.scalar(
            select(func.count()).select_from(CanonEntry).where(CanonEntry.tmdb_id.is_not(None))
        )
        or 0
    )
    unresolvable = (
        session.scalar(
            select(func.count())
            .select_from(CanonEntry)
            .where(CanonEntry.review_status == "unresolvable")
        )
        or 0
    )
    owned = (
        session.scalar(
            select(func.count(func.distinct(CanonEntry.tmdb_id)))
            .select_from(CanonEntry)
            .join(Movie, Movie.tmdb_id == CanonEntry.tmdb_id)
            .where(Movie.in_plex.is_(True))
        )
        or 0
    )
    return {
        "total": int(total),
        "owned": int(owned),
        "resolved": int(resolved),
        "unresolved": int(total - resolved - unresolvable),
        "unresolvable": int(unresolvable),
    }
