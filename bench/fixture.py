"""A deterministic synthetic library to benchmark against.

Real numbers need a real shape, and Sift's shape is lopsided: a few thousand
films, an order of magnitude more episodes, a long tail of titles nobody has
watched, and a handful of very large files that dominate the reclaim total. A
uniform random library would make every benchmark look flat and hide exactly the
cases the code exists to handle.

Everything here is seeded. The same seed must produce byte-identical fixtures on
any machine, or a before/after comparison measures the fixture instead of the
change.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from sift.db.models import (
    Episode,
    MediaFile,
    Movie,
    Rating,
    Season,
    Show,
    WatchHistory,
)
from sift.db.session import init_db, make_engine, make_session_factory

GB = 1_000_000_000
HOUR_MS = 3_600_000

# The four rungs a file can sit on, with a plausible bytes-per-hour for each. The
# 4K rate is deliberately ~4x the 1080p one: a benchmark that cannot tell a large
# 4K remux from a bloated 1080p rip is not measuring the thing that matters.
_RUNGS = (
    ("480p", 720, 480, "h264", 1.1 * GB),
    ("720p", 1280, 720, "h264", 2.4 * GB),
    ("1080p", 1920, 1080, "h264", 4.5 * GB),
    ("2160p", 3840, 2160, "hevc", 17.0 * GB),
)

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def build_library(
    db_path: Path,
    *,
    films: int = 2000,
    shows: int = 120,
    seasons_per_show: int = 4,
    episodes_per_season: int = 12,
    seed: int = 20260813,
) -> sessionmaker[Session]:
    """Create a fixture database and return a session factory for it."""
    engine = make_engine(db_path)
    init_db(engine)
    factory = make_session_factory(engine)
    rng = random.Random(seed)

    with factory() as session:
        _films(session, rng, films)
        _television(session, rng, shows, seasons_per_show, episodes_per_season)
        session.commit()
    return factory


def _films(session: Session, rng: random.Random, count: int) -> None:
    for n in range(count):
        tmdb_id = 100_000 + n
        rung, width, height, codec, rate = _RUNGS[_weighted_rung(rng)]
        hours = rng.uniform(1.4, 2.6)
        # One film in forty is a genuine outlier — a remux, or a broken rip. These
        # are what the reclaim ledger is for, so a fixture without them measures
        # nothing interesting.
        multiplier = 1.0
        if n % 40 == 0:
            multiplier = rng.uniform(3.0, 6.0)
        elif n % 97 == 0:
            multiplier = 0.08

        session.add(
            Movie(
                tmdb_id=tmdb_id,
                title=f"Film {n}",
                year=1970 + (n % 56),
                in_plex=True,
                is_kids=(n % 11 == 0),
                runtime=int(hours * 60),
                file_size=int(rate * hours * multiplier),
                quality=rung,
                plex_rating_key=str(500_000 + n),
                us_theatrical=(n % 5 == 0),
                budget=rng.choice([0, 1_000_000, 40_000_000]),
                added_at=_EPOCH - timedelta(days=rng.randint(1, 2000)),
            )
        )
        session.add(
            Rating(
                movie_id=tmdb_id,
                source="tmdb",
                value=round(rng.uniform(3.0, 8.5), 1),
                votes=rng.choice([12, 90, 400, 5000, 40_000]),
            )
        )
        session.add(
            MediaFile(
                movie_tmdb_id=tmdb_id,
                path=f"/films/{tmdb_id}/film.mkv",
                size=int(rate * hours * multiplier),
                duration_ms=int(hours * HOUR_MS),
                width=width,
                height=height,
                resolution=rung,
                video_codec=codec,
                source="plex",
                seen_at=_EPOCH,
            )
        )
        # Two thirds of the library has never been played. That skew is the whole
        # premise of the junk score, so a fixture that watches everything evenly
        # would score uniformly and measure nothing.
        if n % 3 == 0:
            session.add(
                WatchHistory(
                    movie_id=tmdb_id,
                    plex_user="Dad" if n % 2 else "Kid",
                    plays=rng.randint(1, 4),
                    last_played_at=_EPOCH - timedelta(days=rng.randint(1, 900)),
                    completion_pct=round(rng.uniform(0.2, 1.0), 3),
                    is_kids_account=(n % 11 == 0),
                )
            )
        if n % 500 == 499:
            session.flush()


def _television(
    session: Session,
    rng: random.Random,
    shows: int,
    seasons_per_show: int,
    episodes_per_season: int,
) -> None:
    for s in range(shows):
        tvdb_id = 200_000 + s
        session.add(
            Show(
                tvdb_id=tvdb_id,
                title=f"Show {s}",
                year=1995 + (s % 30),
                in_plex=True,
                is_kids=(s % 7 == 0),
                runtime=rng.choice([22, 45]),
                plex_rating_key=str(900_000 + s),
                library_section="Anime" if s % 9 == 0 else "TV Shows",
            )
        )
        for season_number in range(1, seasons_per_show + 1):
            season = Season(
                show_id=tvdb_id,
                season_number=season_number,
                air_year=1995 + (s % 30) + season_number,
                episode_count=episodes_per_season,
                episode_file_count=episodes_per_season,
            )
            session.add(season)
            session.flush()
            rung, width, height, codec, rate = _RUNGS[_weighted_rung(rng)]
            for number in range(1, episodes_per_season + 1):
                episode = Episode(
                    season_id=season.id,
                    episode_number=number,
                    title=f"S{season_number}E{number}",
                    has_file=True,
                )
                session.add(episode)
                session.flush()
                hours = rng.choice([0.37, 0.75])
                size = int(rate * hours)
                session.add(
                    MediaFile(
                        episode_id=episode.id,
                        path=f"/tv/{tvdb_id}/s{season_number:02d}e{number:02d}.mkv",
                        size=size,
                        duration_ms=int(hours * HOUR_MS),
                        width=width,
                        height=height,
                        resolution=rung,
                        video_codec=codec,
                        source="plex",
                        seen_at=_EPOCH,
                    )
                )
                # Every twelfth episode is duplicated. Duplicates are tier-0 — the
                # safest bytes in the ledger — so their share of the total is a
                # headline the benchmark should be able to move.
                if number % 12 == 0:
                    session.add(
                        MediaFile(
                            episode_id=episode.id,
                            path=f"/tv/{tvdb_id}/s{season_number:02d}e{number:02d}.dup.mkv",
                            size=int(size * 0.8),
                            duration_ms=int(hours * HOUR_MS),
                            width=width,
                            height=height,
                            resolution=rung,
                            video_codec=codec,
                            source="plex",
                            seen_at=_EPOCH,
                        )
                    )


def _weighted_rung(rng: random.Random) -> int:
    """Libraries are mostly 1080p with a 4K minority — not uniform across rungs."""
    roll = rng.random()
    if roll < 0.10:
        return 0
    if roll < 0.25:
        return 1
    if roll < 0.90:
        return 2
    return 3


def summarize(factory: sessionmaker[Session]) -> dict[str, Any]:
    from sqlalchemy import func, select

    with factory() as session:
        return {
            "films": session.scalar(select(func.count()).select_from(Movie)),
            "shows": session.scalar(select(func.count()).select_from(Show)),
            "episodes": session.scalar(select(func.count()).select_from(Episode)),
            "media_files": session.scalar(select(func.count()).select_from(MediaFile)),
        }
