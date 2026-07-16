"""Taste profile — weighted aggregation over the Plex library.

Aggregates genres / keywords / people / eras from what you own. Emphasis weights
are user-editable and persist in the singleton ``profile`` row (they'll feed
recommendation ranking once embeddings land).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Movie, MoviePerson, Person, Profile

DEFAULT_WEIGHTS = {"genre": 0.5, "director": 0.5, "cast": 0.5, "keywords": 0.5, "era": 0.5}


def _top(counter: Counter[str], n: int) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in counter.most_common(n)]


def compute(session: Session) -> dict[str, Any]:
    movies = list(session.scalars(select(Movie).where(Movie.in_plex.is_(True))))
    genres: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    eras: Counter[str] = Counter()
    for m in movies:
        genres.update(m.genres or [])
        keywords.update(m.keywords or [])
        if m.year:
            eras[f"{(m.year // 10) * 10}s"] += 1

    directors: Counter[str] = Counter()
    actors: Counter[str] = Counter()
    for mp, person in session.execute(
        select(MoviePerson, Person).join(Person, Person.id == MoviePerson.person_id)
    ):
        if mp.job == "director":
            directors[person.name] += 1
        elif mp.job == "actor":
            actors[person.name] += 1

    return {
        "genres": _top(genres, 8),
        "keywords": _top(keywords, 20),
        "directors": _top(directors, 8),
        "actors": _top(actors, 8),
        "eras": sorted(
            ({"name": k, "count": v} for k, v in eras.items()), key=lambda e: e["name"]
        ),
        "library_size": len(movies),
    }


def get_weights(session: Session) -> dict[str, float]:
    row = session.get(Profile, 1)
    if row and row.weights:
        return {**DEFAULT_WEIGHTS, **row.weights}
    return dict(DEFAULT_WEIGHTS)


def set_weights(session: Session, weights: dict[str, float]) -> dict[str, float]:
    clean = {k: float(v) for k, v in weights.items() if k in DEFAULT_WEIGHTS}
    row = session.get(Profile, 1)
    if row is None:
        row = Profile(id=1, weights={**DEFAULT_WEIGHTS, **clean})
        session.add(row)
    else:
        row.weights = {**DEFAULT_WEIGHTS, **(row.weights or {}), **clean}
    session.commit()
    return get_weights(session)
