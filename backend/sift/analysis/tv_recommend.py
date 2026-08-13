"""A short list of shows you might want next.

Deliberately short. Twenty-four film suggestions is a browse; twenty-four show
suggestions is a second job. A series is dozens of hours, so the useful answer is
a handful you might genuinely start — and a list nobody finishes reading is worse
than a list half its length.

**The seeds are shows you actually watched, not shows you rate highly.** For
films a rating is a fair proxy for taste, because watching one is a small
commitment and most owned films have been seen. Television is different: a
library is full of shows acquired and never started, and any of those seeding the
recommendations would send it somewhere you have already declined to go. Finishing
episodes is the signal that survives that.

Nothing here decides anything. Suggestions are things to look at, and a show only
arrives on the server when you ask for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Show

# How many suggestions to return. Small on purpose — see the module docstring.
DEFAULT_LIMIT = 8

# How many watched shows seed the search. More anchors means a broader, blander
# spread; a few well-watched ones keep the suggestions recognisably yours.
_ANCHOR_COUNT = 8

# Below this, a show was sampled rather than watched, and sampling something is
# not an endorsement of it.
_MIN_COMPLETION = 0.5

# A suggestion needs enough votes to be a real show rather than a listing. Lower
# than the film equivalent because television accumulates fewer TMDB votes.
_MIN_VOTES = 150


@dataclass(frozen=True)
class Anchor:
    tvdb_id: int
    tmdb_id: int
    title: str
    weight: float


@dataclass(frozen=True)
class Suggestion:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    poster_path: str | None
    vote_average: float | None
    vote_count: int | None
    score: float
    # The shows of yours that led here, so a suggestion can be argued with.
    because_of: list[str]


def anchors(session: Session) -> tuple[list[Anchor], set[int]]:
    """Shows you actually watched, and the TMDB ids of everything you already have.

    Ordered by how completely you watched them, then by how much. A show watched
    to 95% twice says more about your taste than one rated highly and never
    started.
    """
    owned: set[int] = set()
    picks: list[Anchor] = []
    rows = session.scalars(
        select(Show)
        .where(Show.tmdb_id.is_not(None))
        .order_by(
            Show.mean_completion.desc().nulls_last(),
            Show.plays.desc(),
        )
    )
    for show in rows:
        if show.tmdb_id:
            owned.add(int(show.tmdb_id))
        if len(picks) >= _ANCHOR_COUNT:
            continue
        completion = show.mean_completion
        if not show.plays or completion is None or completion < _MIN_COMPLETION:
            continue
        picks.append(
            Anchor(
                tvdb_id=show.tvdb_id,
                tmdb_id=int(show.tmdb_id or 0),
                title=show.title,
                # 0.5 completion earns half a vote, 1.0 earns a full one.
                weight=max(0.3, min(1.0, float(completion))),
            )
        )
    return picks, owned


def rank(
    candidates: dict[int, tuple[dict[str, Any], list[str], float]],
    *,
    owned: set[int],
    limit: int = DEFAULT_LIMIT,
) -> list[Suggestion]:
    """Turn raw TMDB results into a short, ordered list.

    Weight is how many of your watched shows point at it and how completely you
    watched them; the rating only breaks ties. A show recommended by three series
    you finished beats one recommended by a single series you half-watched, even
    if the latter is better reviewed.
    """
    out: list[Suggestion] = []
    for tmdb_id, (raw, because, weight) in candidates.items():
        if tmdb_id in owned:
            continue
        votes = raw.get("vote_count")
        if not votes or int(votes) < _MIN_VOTES:
            # Not obscure-and-interesting, just unverifiable.
            continue
        first_air = str(raw.get("first_air_date") or "")
        rating = raw.get("vote_average")
        out.append(
            Suggestion(
                tmdb_id=tmdb_id,
                title=str(raw.get("name") or raw.get("original_name") or ""),
                year=int(first_air[:4]) if first_air[:4].isdigit() else None,
                overview=str(raw.get("overview") or ""),
                poster_path=raw.get("poster_path"),
                vote_average=float(rating) if rating is not None else None,
                vote_count=int(votes),
                score=round(weight + (float(rating or 0) / 100.0), 4),
                because_of=because[:3],
            )
        )
    out.sort(key=lambda s: s.score, reverse=True)
    return out[: max(1, limit)]


async def suggest(
    factory: Any,
    settings: Any,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[Suggestion]:
    """Walk TMDB's television graph out from the shows you finished.

    Returns an empty list rather than raising when TMDB isn't configured — no
    suggestions is a legitimate state, and a screen that errors because an
    optional service is absent is worse than one that says it found nothing.
    """
    from ..clients.tmdb import TmdbClient

    if not settings.tmdb.enabled or not settings.tmdb.api_key:
        return []
    with factory() as session:
        seeds, owned = anchors(session)
    if not seeds:
        return []

    candidates: dict[int, tuple[dict[str, Any], list[str], float]] = {}
    client = TmdbClient(settings.tmdb)
    try:
        for anchor in seeds:
            if not anchor.tmdb_id:
                continue
            for fetch in (client.get_tv_recommendations, client.get_similar_tv):
                try:
                    results = await fetch(anchor.tmdb_id)
                except Exception:  # noqa: BLE001 - one dead seed must not kill the list
                    continue
                for raw in results:
                    tmdb_id = raw.get("id")
                    if not tmdb_id:
                        continue
                    existing = candidates.get(int(tmdb_id))
                    if existing is None:
                        candidates[int(tmdb_id)] = (raw, [anchor.title], anchor.weight)
                    else:
                        _raw, because, weight = existing
                        if anchor.title not in because:
                            because.append(anchor.title)
                        candidates[int(tmdb_id)] = (_raw, because, weight + anchor.weight)
    finally:
        await client.aclose()
    return rank(candidates, owned=owned, limit=limit)
