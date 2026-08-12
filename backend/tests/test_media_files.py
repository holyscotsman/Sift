"""Capturing the file detail that was already being fetched and thrown away.

``Movie.file_size`` is a bare byte count, so nothing downstream could tell a
three-hour 4K remux from a bloated ninety-minute 1080p. These pin that duration,
resolution and codec now survive ingest, and that a title held twice reports the
disk both copies actually occupy.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from sift.db.models import MediaFile
from sift.ingest import normalize
from sift.ingest.pipeline import ScanPipeline


def _part(file: str, size: int, duration: int) -> dict:
    return {"file": file, "size": size, "duration": duration, "container": "mkv"}


def _plex_item(rating_key: str, tmdb_id: int, title: str, *, media: list | None = None) -> dict:
    raw = {
        "ratingKey": rating_key,
        "title": title,
        "year": 1999,
        "Guid": [{"id": f"tmdb://{tmdb_id}"}],
        "Media": media if media is not None else [],
    }
    return normalize.normalize_plex_item(raw, section_title="Movies", is_kids=False)


# ------------------------------------------------------------------ pure parsing


@pytest.mark.parametrize(
    ("height", "fallback", "expected"),
    [
        (2160, None, "2160p"),
        (1080, None, "1080p"),
        (800, None, "1080p"),  # scope framing is still a 1080p master
        (720, None, "720p"),
        (480, None, "480p"),
        (None, "4k", "2160p"),
        (None, "sd", "480p"),
        (None, "", None),
    ],
)
def test_resolution_ladder(height, fallback, expected):
    assert normalize.resolution_label(height, fallback) == expected


def test_the_ladder_reads_height_not_width():
    """NEGATIVE CONTROL: a scope film is letterboxed, so its height sits a rung or
    two below its width. Judging on width files every one of them too high, and an
    over-stated rung raises the expected bitrate — turning ordinary files into
    apparent bargains and hiding the bloated ones."""
    scope = normalize.normalize_media_info(
        {"resolution": "1920x800", "duration": 8_160_000}, size=8_000_000_000, source="plex"
    )
    assert scope is not None
    assert (scope["width"], scope["height"]) == (1920, 800)
    assert scope["resolution"] == "1080p"  # not 2160p, which the width would imply

    uhd_scope = normalize.normalize_media_info(
        {"resolution": "3840x1600", "duration": 8_160_000}, size=8_000_000_000, source="plex"
    )
    assert uhd_scope is not None
    assert uhd_scope["resolution"] == "1440p"
    assert normalize.resolution_label(1601) == "2160p"


def test_radarr_runtime_string_becomes_milliseconds():
    assert normalize.parse_duration_ms("01:52:30") == 6_750_000
    assert normalize.parse_duration_ms("00:00:08.500") == 8_500
    assert normalize.parse_duration_ms(6_750_000) == 6_750_000


def test_unparseable_duration_is_absent_not_zero():
    """NEGATIVE CONTROL: a zero would divide into an infinite bitrate and flag
    every unparsed file as an outlier. Absence must stay absence."""
    assert normalize.parse_duration_ms("not a duration") is None
    assert normalize.parse_duration_ms("") is None
    assert normalize.parse_duration_ms(0) is None


def test_codec_spellings_fold_to_one_name():
    for spelling in ("HEVC", "x265", "h.265", "hvc1"):
        assert normalize._codec(spelling) == "h265"
    for spelling in ("AVC", "x264", "h.264"):
        assert normalize._codec(spelling) == "h264"


def test_a_record_with_no_size_and_no_duration_is_dropped():
    """NEGATIVE CONTROL: storing it would create a row that every bitrate query
    has to guard against, in exchange for no information at all."""
    assert normalize.normalize_media_info({"videoCodec": "h264"}, source="plex") is None
    assert normalize.normalize_media_info({}, size=1, source="plex") is not None


# ------------------------------------------------------------------ plex parsing


def test_plex_media_block_is_no_longer_discarded():
    item = _plex_item(
        "1001",
        603,
        "The Matrix",
        media=[
            {
                "width": 1920,
                "height": 1080,
                "videoCodec": "hevc",
                "audioCodec": "eac3",
                "Part": [_part("/movies/matrix.mkv", 8_000_000_000, 8_160_000)],
            }
        ],
    )
    (record,) = item["media_files"]
    assert record["size"] == 8_000_000_000
    assert record["duration_ms"] == 8_160_000
    assert record["resolution"] == "1080p"
    assert record["video_codec"] == "h265"
    assert record["path"] == "/movies/matrix.mkv"


def test_every_version_and_part_is_counted():
    """Plex models alternate versions as several Media and a split file as several
    Part. Keeping only the first would under-report the disk in use."""
    item = _plex_item(
        "1001",
        603,
        "The Matrix",
        media=[
            {"height": 1080, "Part": [_part("/a.mkv", 8_000_000_000, 8_160_000)]},
            {
                "height": 480,
                "Part": [
                    _part("/b-cd1.avi", 700_000_000, 4_080_000),
                    _part("/b-cd2.avi", 700_000_000, 4_080_000),
                ],
            },
        ],
    )
    assert len(item["media_files"]) == 3
    assert sum(r["size"] for r in item["media_files"]) == 9_400_000_000


def test_an_item_with_no_media_block_yields_nothing():
    """NEGATIVE CONTROL: an item Plex reports without files must not invent one."""
    assert _plex_item("1001", 603, "The Matrix")["media_files"] == []


# --------------------------------------------------------------- radarr parsing


def test_radarr_media_info_is_read_from_the_payload_already_fetched():
    raw = {
        "tmdbId": 603,
        "title": "The Matrix",
        "hasFile": True,
        "sizeOnDisk": 8_000_000_000,
        "movieFile": {
            "path": "/movies/matrix.mkv",
            "size": 8_000_000_000,
            "quality": {"quality": {"name": "Bluray-1080p"}},
            "mediaInfo": {
                "runTime": "02:16:00",
                "resolution": "1920x1080",
                "videoCodec": "x264",
                "audioCodec": "DTS",
            },
        },
    }
    record = normalize.normalize_radarr_movie(raw)["media_file"]
    assert record["duration_ms"] == 8_160_000
    assert record["resolution"] == "1080p"
    assert record["video_codec"] == "h264"
    assert record["source"] == "radarr"


def test_a_movie_with_no_file_reports_no_media():
    """NEGATIVE CONTROL: a monitored-but-absent title occupies no disk."""
    raw = {"tmdbId": 603, "title": "The Matrix", "hasFile": False, "movieFile": {}}
    assert normalize.normalize_radarr_movie(raw)["media_file"] is None


# -------------------------------------------------------------------- persistence


def test_files_survive_a_rescan_without_accumulating(factory, settings):
    pipe = ScanPipeline(factory, settings)
    items = [
        _plex_item(
            "1001",
            603,
            "The Matrix",
            media=[{"height": 1080, "Part": [_part("/a.mkv", 8_000_000_000, 8_160_000)]}],
        )
    ]
    pipe._persist_plex(items)
    pipe._persist_plex(items)
    with factory() as session:
        rows = list(session.scalars(select(MediaFile)))
    assert len(rows) == 1
    assert rows[0].size == 8_000_000_000


def test_a_file_plex_stops_reporting_is_removed(factory, settings):
    """NEGATIVE CONTROL: a deleted rip that lingers keeps being counted as disk
    you could reclaim, which is the one number this feature must not overstate."""
    pipe = ScanPipeline(factory, settings)
    two = [
        _plex_item(
            "1001",
            603,
            "The Matrix",
            media=[
                {"height": 1080, "Part": [_part("/a.mkv", 8_000_000_000, 8_160_000)]},
                {"height": 480, "Part": [_part("/b.avi", 700_000_000, 8_160_000)]},
            ],
        )
    ]
    pipe._persist_plex(two)
    with factory() as session:
        assert len(list(session.scalars(select(MediaFile)))) == 2

    one = [
        _plex_item(
            "1001",
            603,
            "The Matrix",
            media=[{"height": 1080, "Part": [_part("/a.mkv", 8_000_000_000, 8_160_000)]}],
        )
    ]
    pipe._persist_plex(one)
    with factory() as session:
        rows = list(session.scalars(select(MediaFile)))
    assert [r.path for r in rows] == ["/a.mkv"]


def test_radarr_does_not_double_count_a_file_plex_already_described(factory, settings):
    """The two mount the same library at different paths, so storing both views
    would report twice the disk that actually exists."""
    pipe = ScanPipeline(factory, settings)
    pipe._persist_plex(
        [
            _plex_item(
                "1001",
                603,
                "The Matrix",
                media=[{"height": 1080, "Part": [_part("/plex/a.mkv", 8_000_000_000, 8_160_000)]}],
            )
        ]
    )
    pipe._persist_radarr(
        [
            normalize.normalize_radarr_movie(
                {
                    "tmdbId": 603,
                    "title": "The Matrix",
                    "hasFile": True,
                    "sizeOnDisk": 8_000_000_000,
                    "movieFile": {
                        "path": "/radarr/a.mkv",
                        "size": 8_000_000_000,
                        "mediaInfo": {"runTime": "02:16:00", "resolution": "1920x1080"},
                    },
                }
            )
        ],
        [],
    )
    with factory() as session:
        rows = list(session.scalars(select(MediaFile)))
    assert [r.source for r in rows] == ["plex"]
    assert sum(r.size or 0 for r in rows) == 8_000_000_000


def test_radarr_fills_the_gap_when_plex_never_saw_the_file(factory, settings):
    pipe = ScanPipeline(factory, settings)
    pipe._persist_radarr(
        [
            normalize.normalize_radarr_movie(
                {
                    "tmdbId": 603,
                    "title": "The Matrix",
                    "hasFile": True,
                    "sizeOnDisk": 8_000_000_000,
                    "movieFile": {
                        "path": "/radarr/a.mkv",
                        "size": 8_000_000_000,
                        "mediaInfo": {"runTime": "02:16:00", "resolution": "1920x1080"},
                    },
                }
            )
        ],
        [],
    )
    with factory() as session:
        rows = list(session.scalars(select(MediaFile)))
    assert [(r.source, r.resolution) for r in rows] == [("radarr", "1080p")]
