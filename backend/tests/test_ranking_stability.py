"""Rankings must not depend on the order the database returns rows in.

SQLite hands rows back in rowid order and always has, which is why this class of
bug is invisible to every other test here. Postgres — what Sift actually runs on —
promises nothing for a SELECT without ORDER BY, and is free to reorder after
updates or a vacuum.

None of the analysis queries specify an order, so any sort whose key is not total
lets two equal-scoring items swap places. The reclaim page shows the first 500
findings, so swapping places is not cosmetic: it changes which findings a person
is shown.
"""

from __future__ import annotations

import pytest

from sift.analysis import ledger, outliers, tv_duplicates, tv_size
from sift.db.models import Episode, MediaFile, Movie, Season, Show

GB = 1_000_000_000


@pytest.fixture
def library(factory):
    """Deliberately full of exact ties — the only case a partial sort key mishandles."""
    with factory() as session:
        # Four films of identical size: nothing but identity can order them.
        for n in range(4):
            tmdb_id = 500 + n
            session.add(
                Movie(tmdb_id=tmdb_id, title=f"Film {n}", year=2001, in_plex=True, runtime=120)
            )
            session.add(
                MediaFile(
                    movie_tmdb_id=tmdb_id, path=f"/films/{tmdb_id}.mkv", size=40 * GB,
                    duration_ms=7_200_000, resolution="1080p", video_codec="h264", source="plex",
                )
            )
        # Four shows, each with one duplicated episode of identical size.
        for s in range(4):
            tvdb_id = 700 + s
            session.add(Show(tvdb_id=tvdb_id, title=f"Show {s}", in_plex=True, runtime=45))
            season = Season(show_id=tvdb_id, season_number=1, air_year=2001)
            session.add(season)
            session.flush()
            for number in range(1, 5):
                episode = Episode(season_id=season.id, episode_number=number, has_file=True)
                session.add(episode)
                session.flush()
                session.add(
                    MediaFile(
                        episode_id=episode.id, path=f"/tv/{tvdb_id}/e{number}.mkv", size=3 * GB,
                        duration_ms=2_700_000, resolution="1080p", video_codec="h264",
                        source="plex",
                    )
                )
                if number == 1:
                    session.add(
                        MediaFile(
                            episode_id=episode.id, path=f"/tv/{tvdb_id}/e{number}.dup.mkv",
                            size=2 * GB, duration_ms=2_700_000, resolution="480p",
                            video_codec="h264", source="plex",
                        )
                    )
        # Three identical kids cartoons, which resolve to tied tier-2 downgrade
        # findings. This is the path that most needs the ledger's own tie-break:
        # _downgrades has no sort of its own, so its output order is exactly the
        # order the season rows arrived in. Without these the ledger test passes
        # on a partial key, because every other source sorts itself.
        for c in range(3):
            tvdb_id = 800 + c
            session.add(
                Show(
                    tvdb_id=tvdb_id, title=f"Cartoon {c}", in_plex=True, is_kids=True,
                    runtime=22, genres=["Animation", "Comedy"], library_section="Cartoons",
                    original_language="en",
                )
            )
            season = Season(show_id=tvdb_id, season_number=1, air_year=1999)
            session.add(season)
            session.flush()
            for number in range(1, 7):
                episode = Episode(season_id=season.id, episode_number=number, has_file=True)
                session.add(episode)
                session.flush()
                session.add(
                    MediaFile(
                        episode_id=episode.id, path=f"/tv/{tvdb_id}/e{number}.mkv", size=6 * GB,
                        duration_ms=1_320_000, resolution="1080p", video_codec="h264",
                        source="plex",
                    )
                )
        session.commit()
    return factory


def _reversed_rows(monkeypatch):
    """Hand every loader its rows in the opposite order, which is a thing a real
    database may do and SQLite never does."""
    real_seasons = tv_size.load_seasons
    real_films = outliers._load_film_files
    monkeypatch.setattr(
        tv_size, "load_seasons",
        lambda sess: dict(reversed(list(real_seasons(sess).items()))),
    )
    monkeypatch.setattr(
        outliers, "_load_film_files", lambda sess: list(reversed(real_films(sess)))
    )


def _order(book) -> list[str]:
    return [f"{f.kind}:{f.target_id}" for f in book.findings]


def test_the_reclaim_ledger_is_the_same_whichever_order_rows_arrive_in(library, monkeypatch):
    with library() as session:
        forwards = _order(ledger.build(session, limit=10_000))

    _reversed_rows(monkeypatch)
    with library() as session:
        backwards = _order(ledger.build(session, limit=10_000))

    assert forwards == backwards
    # The tier-2 findings are the ones that need this: they are appended in the
    # order their rows arrived and are not sorted by their own producer.
    assert sum(1 for f in forwards if f.startswith("quality_downgrade")) == 3


@pytest.fixture
def films_only(factory):
    """Films alone, deliberately separate from ``library``.

    Baselines are measured from the library's own files, so the television in
    ``library`` moves the 1080p median and the films stop reading as outliers at
    all. That is the baseline design working; it just makes that fixture the wrong
    place to ask an outlier-ordering question.
    """
    with factory() as session:
        for n in range(4):
            tmdb_id = 500 + n
            session.add(
                Movie(tmdb_id=tmdb_id, title=f"Film {n}", year=2001, in_plex=True, runtime=120)
            )
            session.add(
                MediaFile(
                    movie_tmdb_id=tmdb_id, path=f"/films/{tmdb_id}.mkv", size=40 * GB,
                    duration_ms=7_200_000, resolution="1080p", video_codec="h264", source="plex",
                )
            )
        # Ordinary films, so the four big ones have something to be outliers against.
        for n in range(20):
            tmdb_id = 600 + n
            session.add(
                Movie(tmdb_id=tmdb_id, title=f"Normal {n}", year=2001, in_plex=True, runtime=120)
            )
            session.add(
                MediaFile(
                    movie_tmdb_id=tmdb_id, path=f"/films/{tmdb_id}.mkv", size=9 * GB,
                    duration_ms=7_200_000, resolution="1080p", video_codec="h264", source="plex",
                )
            )
        session.commit()
    return factory


def test_film_outliers_hold_their_order(films_only, monkeypatch):
    library = films_only
    with library() as session:
        forwards = [f.tmdb_id for f in outliers.find(session, limit=10_000).findings]
    _reversed_rows(monkeypatch)
    with library() as session:
        backwards = [f.tmdb_id for f in outliers.find(session, limit=10_000).findings]
    assert forwards == backwards
    assert len(forwards) == 4


def test_duplicate_shows_hold_their_order(library):
    """Four shows with identical reclaimable bytes: only the identity tie-break
    can decide, and it must decide the same way twice."""
    with library() as session:
        first, _ = tv_duplicates.find(session, limit=10_000)
    with library() as session:
        second, _ = tv_duplicates.find(session, limit=10_000)
    # Asserted against the order the tie-break defines, not merely against a
    # second run: hash-based or arbitrary orderings are stable within one process,
    # so run-to-run equality alone would pass on a broken key.
    assert [s.tvdb_id for s in first] == [700, 701, 702, 703]
    assert [s.tvdb_id for s in second] == [700, 701, 702, 703]
    assert len({s.reclaimable for s in first}) == 1, "the shows must genuinely tie"
