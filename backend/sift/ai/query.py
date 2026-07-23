"""Grounded Q&A over the snapshot.

Retrieval is deterministic (keyword match over the Plex library); the provider only
phrases an answer from that bounded context and is instructed not to invent titles.
This keeps answers grounded and prevents hallucinated movies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Movie
from .provider import LLMProvider

_SYSTEM = (
    "You are Sift, an assistant for a personal Plex movie library. Answer ONLY using "
    "the library context provided. Do not invent titles that aren't in the context. If "
    "the context doesn't contain the answer, say so plainly. Be concise and reference "
    "movie titles exactly as given."
)


@dataclass(frozen=True)
class Source:
    tmdb_id: int
    title: str
    year: int | None


@dataclass(frozen=True)
class AskResult:
    answer: str
    provider: str
    model: str
    latency_ms: float
    sources: list[Source]


def retrieve(session: Session, query: str, *, limit: int = 12) -> list[Movie]:
    terms = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 3]
    base = select(Movie).where(Movie.in_plex.is_(True))
    stmt = base
    if terms:
        conds = []
        for t in terms:
            like = f"%{t}%"
            conds.append(func.lower(Movie.title).like(like))
            conds.append(func.lower(func.coalesce(Movie.overview, "")).like(like))
            conds.append(func.lower(cast(Movie.genres, String)).like(like))
            conds.append(func.lower(cast(Movie.keywords, String)).like(like))
        stmt = base.where(or_(*conds))
    stmt = stmt.order_by(Movie.year.desc().nulls_last()).limit(limit)
    rows = list(session.scalars(stmt))
    if not rows and terms:  # nothing matched — ground on a sample of the library
        rows = list(session.scalars(base.order_by(Movie.year.desc().nulls_last()).limit(limit)))
    return rows


def _context(movies: list[Movie]) -> str:
    lines = []
    for m in movies:
        genres = ", ".join(m.genres or [])
        lines.append(
            f"- {m.title} ({m.year or '?'}) — {genres or 'n/a'}"
            f"{f' — {m.library_section}' if m.library_section else ''}"
        )
    return "\n".join(lines) if lines else "(the library is empty)"


async def answer_with(provider: LLMProvider, movies: list[Movie], query: str) -> AskResult:
    """Phrase an answer over an already-retrieved context. Split out so compare
    mode can ask two providers about the SAME retrieval (comparable answers)."""
    prompt = f"Library context ({len(movies)} titles):\n{_context(movies)}\n\nQuestion: {query}"
    completion = await provider.complete(system=_SYSTEM, prompt=prompt)
    return AskResult(
        answer=completion.text,
        provider=completion.provider,
        model=completion.model,
        latency_ms=completion.latency_ms,
        sources=[Source(m.tmdb_id, m.title, m.year) for m in movies],
    )


async def answer(
    session: Session, provider: LLMProvider, query: str, *, limit: int = 12
) -> AskResult:
    movies = retrieve(session, query, limit=limit)
    return await answer_with(provider, movies, query)
