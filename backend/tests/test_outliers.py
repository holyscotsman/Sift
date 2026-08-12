"""Movie size outliers, and above all the small-file discrimination.

The dangerous mistake this module could make is deleting a genuine short film
because it is small. Every control below is about keeping that from happening.
"""

from __future__ import annotations

import pytest

from sift.analysis import outliers
from sift.db.models import MediaFile, Movie

GB = 1_000_000_000
HOUR_MS = 3_600_000
MIN_MS = 60_000


@pytest.fixture
def library(factory):
    """A library of ordinary 1080p h264 films, so the baselines are trustworthy."""

    def _build(extra: list[tuple[dict, dict]] | None = None) -> None:
        with factory() as session:
            for i in range(10):
                tmdb_id = 1000 + i
                session.add(Movie(tmdb_id=tmdb_id, title=f"Ordinary {i}", year=2015, runtime=120))
                session.add(
                    MediaFile(
                        movie_tmdb_id=tmdb_id,
                        path=f"/movies/ordinary{i}.mkv",
                        size=6 * GB,
                        duration_ms=2 * HOUR_MS,
                        resolution="1080p",
                        video_codec="h264",
                        source="plex",
                    )
                )
            for movie_kwargs, file_kwargs in extra or []:
                session.add(Movie(**movie_kwargs))
                session.add(MediaFile(**file_kwargs))
            session.commit()

    return _build


def _film(tmdb_id: int, title: str, runtime: int | None) -> dict:
    return {"tmdb_id": tmdb_id, "title": title, "year": 2015, "runtime": runtime}


def _file(tmdb_id: int, *, size: int, duration_ms: int, resolution="1080p", codec="h264") -> dict:
    return {
        "movie_tmdb_id": tmdb_id,
        "path": f"/movies/{tmdb_id}.mkv",
        "size": size,
        "duration_ms": duration_ms,
        "resolution": resolution,
        "video_codec": codec,
        "source": "plex",
    }


# ------------------------------------------------------------------- too large


def test_a_bloated_1080p_film_is_flagged_with_its_excess(library, factory):
    library([(_film(9001, "Bloated", 90), _file(9001, size=30 * GB, duration_ms=90 * MIN_MS))])
    with factory() as session:
        report = outliers.find(session)
    hit = next(f for f in report.findings if f.tmdb_id == 9001)
    assert hit.kind == "oversized"
    assert hit.bytes_reclaimable > 20 * GB
    assert report.total_reclaimable >= hit.bytes_reclaimable


def test_a_long_4k_film_of_the_same_size_is_left_alone(library, factory):
    """NEGATIVE CONTROL: identical byte count, different film. Judged on size
    alone this is condemned; judged per hour and per resolution it is ordinary."""
    library(
        [
            (
                _film(9002, "Long 4K", 180),
                _file(9002, size=30 * GB, duration_ms=3 * HOUR_MS, resolution="2160p"),
            )
        ]
    )
    with factory() as session:
        report = outliers.find(session)
    assert all(f.tmdb_id != 9002 for f in report.findings)


# ------------------------------------------------------------------- too small


def test_a_genuine_short_film_is_never_flagged(library, factory):
    """The mistake that would matter most. A 22-minute film in a 400 MB file is
    correct, and nothing about it should reach a removal queue."""
    library([(_film(9003, "A Short", 22), _file(9003, size=400_000_000, duration_ms=22 * MIN_MS))])
    with factory() as session:
        report = outliers.find(session)
    assert all(f.tmdb_id != 9003 for f in report.findings)
    assert report.short_films_cleared == 1


def test_a_truncated_feature_is_flagged_for_the_whole_file(library, factory):
    library(
        [(_film(9004, "Cut Short", 120), _file(9004, size=200_000_000, duration_ms=8 * MIN_MS))]
    )
    with factory() as session:
        report = outliers.find(session)
    hit = next(f for f in report.findings if f.tmdb_id == 9004)
    assert hit.kind == "truncated"
    assert hit.risk_tier == 0  # nothing of value is lost
    assert hit.bytes_reclaimable == 200_000_000


def test_the_discriminator_is_duration_against_runtime_not_size(library, factory):
    """Two files of exactly the same size, one fine and one broken. Only the
    published runtime separates them — which is why removing that comparison
    cannot be caught by any size threshold."""
    library(
        [
            (_film(9005, "Short", 20), _file(9005, size=300_000_000, duration_ms=20 * MIN_MS)),
            (_film(9006, "Broken", 130), _file(9006, size=300_000_000, duration_ms=6 * MIN_MS)),
        ]
    )
    with factory() as session:
        report = outliers.find(session)
    flagged = {f.tmdb_id: f.kind for f in report.findings}
    assert 9005 not in flagged
    assert flagged[9006] == "truncated"


def test_a_complete_but_terrible_rip_is_replaced_not_deleted(library, factory):
    """It is the whole film, so its bytes are not reclaimable — you keep using
    them until a better copy arrives. Counting them would pad the total with disk
    that is never actually freed."""
    library(
        [(_film(9007, "Murky", 120), _file(9007, size=500_000_000, duration_ms=2 * HOUR_MS))]
    )
    with factory() as session:
        report = outliers.find(session)
    hit = next(f for f in report.findings if f.tmdb_id == 9007)
    assert hit.kind == "bad_rip"
    assert hit.bytes_reclaimable == 0


def test_a_small_file_with_no_published_runtime_gets_no_verdict(library, factory):
    """NEGATIVE CONTROL: without the comparison there is no way to tell a short
    film from a broken one, and a delete proposed on a guess is unrecoverable."""
    library([(_film(9008, "Unknown", None), _file(9008, size=200_000_000, duration_ms=8 * MIN_MS))])
    with factory() as session:
        report = outliers.find(session)
    assert all(f.tmdb_id != 9008 for f in report.findings)


def test_an_empty_library_reports_nothing(factory):
    """NEGATIVE CONTROL: no files, no findings, no crash on absent baselines."""
    with factory() as session:
        report = outliers.find(session)
    assert report.findings == []
    assert report.total_reclaimable == 0


def test_findings_are_ranked_by_what_they_return(library, factory):
    library(
        [
            (_film(9009, "Big", 90), _file(9009, size=30 * GB, duration_ms=90 * MIN_MS)),
            (_film(9010, "Bigger", 90), _file(9010, size=45 * GB, duration_ms=90 * MIN_MS)),
        ]
    )
    with factory() as session:
        report = outliers.find(session)
    reclaimable = [f.bytes_reclaimable for f in report.findings]
    assert reclaimable == sorted(reclaimable, reverse=True)
