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
    """Recount the library. Called on every view of the profile page.

    Columns, not entities. The profile counts three things about a film — its
    genres, its keywords and its decade — while ``select(Movie)`` ships all
    thirty-one columns for every film owned, ``overview`` and ``poster_url``
    included. Those two alone are larger than everything this function reads, and
    a hosted database meters bytes moved rather than statements, so the whole-row
    read cost more than the page it draws. The same applies to the credits join,
    which needs a job and a name out of two fully hydrated rows per credit — and
    there are a dozen credits per film.
    """
    library = session.execute(
        select(Movie.genres, Movie.keywords, Movie.year).where(Movie.in_plex.is_(True))
    ).all()
    genres: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    eras: Counter[str] = Counter()
    for movie_genres, movie_keywords, year in library:
        genres.update(movie_genres or [])
        keywords.update(movie_keywords or [])
        if year:
            eras[f"{(year // 10) * 10}s"] += 1

    directors: Counter[str] = Counter()
    actors: Counter[str] = Counter()
    for job, name in session.execute(
        select(MoviePerson.job, Person.name).join(Person, Person.id == MoviePerson.person_id)
    ):
        if job == "director":
            directors[name] += 1
        elif job == "actor":
            actors[name] += 1

    return {
        "genres": _top(genres, 8),
        "keywords": _top(keywords, 20),
        "directors": _top(directors, 8),
        "actors": _top(actors, 8),
        "eras": sorted(
            ({"name": k, "count": v} for k, v in eras.items()), key=lambda e: e["name"]
        ),
        "library_size": len(library),
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
