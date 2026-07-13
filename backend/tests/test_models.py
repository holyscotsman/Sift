"""Model + schema smoke tests, including FK cascade."""

from __future__ import annotations

from sqlalchemy import select

from sift.db.models import Movie, Rating, RatingSource, WatchHistory


def test_insert_movie_with_children_and_cascade(factory):
    with factory() as session:
        movie = Movie(tmdb_id=27205, title="Inception", year=2010, has_file=True)
        movie.ratings.append(Rating(source=RatingSource.TMDB, value=8.3, votes=30000))
        movie.watch_history.append(WatchHistory(plex_user="Dad", plays=2, completion_pct=0.9))
        session.add(movie)
        session.commit()

    with factory() as session:
        stored = session.get(Movie, 27205)
        assert stored is not None
        assert stored.ratings[0].value == 8.3
        assert stored.watch_history[0].plays == 2

    # Deleting the movie cascades to ratings/watch_history.
    with factory() as session:
        session.delete(session.get(Movie, 27205))
        session.commit()
    with factory() as session:
        assert session.scalars(select(Rating)).first() is None
        assert session.scalars(select(WatchHistory)).first() is None
