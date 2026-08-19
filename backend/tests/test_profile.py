"""Taste profile aggregation + editable weights."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import Movie
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_profile_aggregates_and_weights(client):
    c, factory = client
    with factory() as session:
        session.add(
            Movie(tmdb_id=1, title="A", year=1999, in_plex=True, genres=["Action", "Sci-Fi"])
        )
        session.add(Movie(tmdb_id=2, title="B", year=1995, in_plex=True, genres=["Action"]))
        # Not in Plex → excluded from the taste profile.
        session.add(Movie(tmdb_id=3, title="C", year=2001, in_plex=False, genres=["Drama"]))
        session.commit()

    body = c.get("/api/profile").json()
    assert body["library_size"] == 2
    genres = {g["name"]: g["count"] for g in body["genres"]}
    assert genres["Action"] == 2 and genres["Sci-Fi"] == 1 and "Drama" not in genres
    assert {e["name"] for e in body["eras"]} == {"1990s"}
    assert body["weights"]["genre"] == 0.5

    updated = c.put("/api/profile/weights", json={
        "genre": 0.9, "director": 0.3, "cast": 0.5, "keywords": 0.5, "era": 0.5,
    }).json()
    assert updated["weights"]["genre"] == 0.9
    assert c.get("/api/profile").json()["weights"]["genre"] == 0.9  # persisted


def test_the_profile_never_reads_the_wide_columns(client):
    """Egress pin, not a round-trip pin.

    The profile page recounts the library every time it is opened, and it counts
    exactly three things about a film: genres, keywords, decade. `select(Movie)`
    ships all thirty-one columns for every film owned — `overview` and
    `poster_url` chief among them, and together larger than everything the page
    actually reads. The credits join had the same shape: a job and a name, taken
    off two fully hydrated rows, a dozen times per film.

    Free on the SQLite these tests run against, which is why it survived. Metered
    by the byte on the database this app is deployed against.
    """
    from sqlalchemy import event

    from sift.db.models import MoviePerson, Person

    c, factory = client
    with factory() as session:
        for i in range(50):
            session.add(
                Movie(
                    tmdb_id=7_000 + i,
                    title=f"Film {i}",
                    year=1999,
                    in_plex=True,
                    genres=["Drama"],
                    keywords=["one"],
                    overview="x" * 600,
                    poster_url="https://image.tmdb.org/t/p/w342/" + "y" * 40,
                )
            )
        session.add(Person(id=1, name="A Director"))
        session.flush()
        for i in range(50):
            session.add(MoviePerson(movie_id=7_000 + i, person_id=1, job="director"))
        session.commit()

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        body = c.get("/api/profile").json()
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    # NEGATIVE CONTROL: the work must actually have happened. A profile that read
    # nothing would pass every assertion below.
    assert body["library_size"] == 50
    assert body["directors"][0] == {"name": "A Director", "count": 50}

    reads = [s for s in seen if s.upper().startswith("SELECT")]
    assert any("FROM movies" in s for s in reads), "nothing read movies at all"
    assert any("FROM movie_people" in s for s in reads), "nothing read the credits at all"
    for column in ("movies.overview", "movies.poster_url", "movies.title", "movie_people.id"):
        offenders = [s for s in reads if column in s]
        assert not offenders, f"the profile read {column} it never uses: {offenders[0][:140]}"
