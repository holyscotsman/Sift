"""Must-Have catalog — AI proposes canon titles, deterministic gates decide.

The engine (whichever providers the AI mode allows) looks at a profile of the
library and proposes widely canonical, mainly theatrical feature films — the
IMDb-top / Criterion-caliber layer of a complete home catalog — that the library
is missing. **Proposals are only ever hints.** Every candidate must survive the
anti-nonsense gates before it is stored:

* it must resolve on TMDB by title+year (hallucinated films die here);
* consensus floor — at least :data:`MIN_VOTES` TMDB votes (fringe uploads die here;
  "I wouldn't watch it" is not a gate, obscurity is);
* quality floor — TMDB average of at least :data:`MIN_RATING`;
* a real feature (runtime ≥ :data:`MIN_RUNTIME` minutes), already released, not
  adult;
* not already in Plex, not previously dismissed by the owner.

With no AI configured the curated starter lists (Criterion / IMDb-top) feed the
same gates, so the feature degrades instead of disappearing. Suggestions never act
on their own — the owner adds or dismisses each one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import Movie, MustHaveSuggestion, Rating
from .provider import LLMProvider
from .registry import build_providers

log = logging.getLogger("sift.ai.musthave")

MIN_VOTES = 200
MIN_RATING = 6.5
MIN_RUNTIME = 60  # minutes — features only, no shorts
_MAX_CANDIDATES = 40  # cap the TMDB validation fan-out per run

SYSTEM = (
    "You are a film curator helping complete a personal home movie library into a "
    "well-rounded catalog. Suggest MUST-HAVE feature films the library is missing: "
    "widely acclaimed theatrical releases, essential classics, and "
    "Criterion-collection-caliber world cinema. Consensus canon only — not personal "
    "taste, not obscure or fringe titles. Respond with STRICT JSON: an array of "
    'objects like [{"title": "...", "year": 1994, "reason": "one short sentence"}] '
    "and nothing else."
)


def _prompt(context: str, limit: int) -> str:
    return (
        f"Library profile:\n{context}\n\n"
        f"Suggest up to {limit} must-have movies this library does NOT already contain. "
        "Prefer breadth across eras and world cinema over more of the same. JSON only."
    )


# ------------------------------------------------------------------ library context


def _library_context(session: Session) -> str:
    """A compact profile: size, top genres, and a sample of the strongest titles."""
    rows = session.execute(
        select(Movie.title, Movie.year, Movie.genres).where(Movie.in_plex.is_(True))
    ).all()
    genre_counts: dict[str, int] = {}
    for _title, _year, genres in rows:
        for g in genres or []:
            genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts, key=lambda g: -genre_counts[g])[:8]

    best = session.execute(
        select(Movie.title, Movie.year, Rating.value)
        .join(Rating, Rating.movie_id == Movie.tmdb_id)
        .where(Movie.in_plex.is_(True))
        .order_by(Rating.value.desc())
        .limit(25)
    ).all()
    sample = ", ".join(f"{t} ({y or '?'})" for t, y, _v in best) or "(no titles yet)"
    return (
        f"{len(rows)} movies. Top genres: {', '.join(top_genres) or 'unknown'}. "
        f"Highest-rated owned titles: {sample}."
    )


def _known_ids(session: Session) -> tuple[set[int], set[int]]:
    """(owned tmdb ids, tmdb ids already suggested or dismissed)."""
    owned = {
        tid for (tid,) in session.execute(select(Movie.tmdb_id).where(Movie.in_plex.is_(True)))
    }
    seen = {tid for (tid,) in session.execute(select(MustHaveSuggestion.tmdb_id))}
    return owned, seen


# ------------------------------------------------------------------- AI orchestration


def parse_titles(text: str) -> list[dict[str, Any]]:
    """Pull the first JSON array out of model output (tolerates markdown fences)."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        year = item.get("year")
        out.append(
            {
                "title": title,
                "year": int(year) if isinstance(year, (int, float)) else None,
                "reason": str(item.get("reason") or "").strip()[:300],
            }
        )
    return out


async def _propose(
    context: str,
    limit: int,
    local: LLMProvider | None,
    anthropic: LLMProvider | None,
) -> tuple[list[dict[str, Any]], str]:
    """Ask the configured engine(s) for candidates. Tandem: local drafts, Claude
    refines the draft into the final list."""
    prompt = _prompt(context, limit)
    draft_text: str | None = None
    if local is not None:
        try:
            draft_text = (await local.complete(system=SYSTEM, prompt=prompt)).text
        except Exception as exc:  # noqa: BLE001 - local is best-effort
            log.info("ollama must-have draft failed: %s", exc)

    if anthropic is not None:
        refine = prompt
        if draft_text:
            refine += (
                f"\n\nA local model drafted this list:\n{draft_text}\n\n"
                "Correct any mistakes, drop weak picks, add stronger ones, and return "
                "the final JSON array."
            )
        try:
            final = (await anthropic.complete(system=SYSTEM, prompt=refine)).text
            titles = parse_titles(final)
            if titles:
                return titles, "anthropic+ollama" if draft_text else "anthropic"
        except Exception as exc:  # noqa: BLE001 - fall back to the draft
            log.info("anthropic must-have pass failed: %s", exc)

    if draft_text:
        titles = parse_titles(draft_text)
        if titles:
            return titles, "ollama"
    return [], "none"


def _curated_fallback(session: Session, limit: int) -> list[dict[str, Any]]:
    """No AI: the Criterion / IMDb-top starter lists feed the same gates."""
    from ..db.models import CuratedListEntry

    labels = {
        "criterion": "the Criterion-caliber starter list",
        "imdb_top": "the IMDb-top starter list",
    }
    rows = session.scalars(
        select(CuratedListEntry).where(CuratedListEntry.list_name.in_(list(labels)))
    ).all()
    return [
        {"title": e.title, "year": e.year, "reason": f"On {labels[e.list_name]}."}
        for e in rows
    ][: limit * 2]


# ------------------------------------------------------------------------ the gates


async def _validate(
    client: TmdbClient, cand: dict[str, Any], owned: set[int], seen: set[int]
) -> dict[str, Any] | None:
    """Return the storable suggestion, or None with the reason logged. AI never
    grades — these checks are pure data."""
    try:
        tmdb_id = await client.search_movie(cand["title"], cand.get("year"))
    except Exception as exc:  # noqa: BLE001 - a search fault just drops the candidate
        log.info("must-have search failed for %r: %s", cand["title"], exc)
        return None
    if tmdb_id is None or tmdb_id in owned or tmdb_id in seen:
        return None
    try:
        detail = await client.get_movie(tmdb_id, append="")
    except Exception as exc:  # noqa: BLE001
        log.info("must-have detail failed for %s: %s", tmdb_id, exc)
        return None
    if not isinstance(detail, dict) or detail.get("adult"):
        return None
    votes = int(detail.get("vote_count") or 0)
    rating = float(detail.get("vote_average") or 0.0)
    runtime = int(detail.get("runtime") or 0)
    release = str(detail.get("release_date") or "")
    released = bool(release) and release <= datetime.now(UTC).date().isoformat()
    if votes < MIN_VOTES or rating < MIN_RATING or runtime < MIN_RUNTIME or not released:
        return None
    year = int(release[:4]) if release[:4].isdigit() else cand.get("year")
    return {
        "tmdb_id": tmdb_id,
        "title": str(detail.get("title") or cand["title"]),
        "year": year,
        "reason": cand.get("reason") or "Widely regarded as essential.",
        "vote_average": round(rating, 1),
        "vote_count": votes,
    }


# ------------------------------------------------------------------------- the run


async def run_musthave(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    limit: int = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Propose, gate, and store must-have suggestions. Returns run counts."""
    if not settings.tmdb.enabled or settings.tmdb.api_key is None:
        return {"added": 0, "considered": 0, "provider": "none", "note": "connect TMDB first"}

    context, owned, seen = await asyncio.to_thread(_read, session_factory)

    local, anthropic = build_providers(settings)
    if local is None and anthropic is None:
        candidates = await asyncio.to_thread(
            _run_in_session, session_factory, lambda s: _curated_fallback(s, limit)
        )
        provider = "curated"
    else:
        candidates, provider = await _propose(context, limit, local, anthropic)
        for prov in (local, anthropic):
            if prov is not None:
                await prov.aclose()

    client = TmdbClient(settings.tmdb, transport=transport)
    accepted: list[dict[str, Any]] = []
    try:
        for cand in candidates[:_MAX_CANDIDATES]:
            if len(accepted) >= limit:
                break
            ok = await _validate(client, cand, owned, seen)
            if ok is not None:
                seen.add(ok["tmdb_id"])  # de-dupe within the run too
                accepted.append(ok)
    finally:
        await client.aclose()

    added = await asyncio.to_thread(_store, session_factory, accepted, provider)
    return {"added": added, "considered": len(candidates), "provider": provider}


def _read(factory: sessionmaker[Session]) -> tuple[str, set[int], set[int]]:
    with factory() as session:
        owned, seen = _known_ids(session)
        return _library_context(session), owned, seen


def _run_in_session(factory: sessionmaker[Session], fn: Any) -> Any:
    with factory() as session:
        return fn(session)


def _store(
    factory: sessionmaker[Session], accepted: list[dict[str, Any]], provider: str
) -> int:
    with factory() as session:
        added = 0
        for item in accepted:
            exists = session.scalars(
                select(MustHaveSuggestion).where(MustHaveSuggestion.tmdb_id == item["tmdb_id"])
            ).first()
            if exists is not None:
                continue
            session.add(MustHaveSuggestion(**item, source=provider))
            added += 1
        session.commit()
        return added
