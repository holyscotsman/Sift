"""TV ingest: shows, seasons, episodes, and the files behind them.

The season is the grain that matters. A show's first year is the wrong ceiling
for its later seasons — Scrubs began in 2001 on SD video and ended in HD — so
these pin that each season carries its own air year rather than inheriting one.
"""

from __future__ import annotations

from sqlalchemy import event, select

from sift.db.models import Episode, MediaFile, Season, Show
from sift.ingest import normalize
from sift.ingest.pipeline import ScanPipeline

GB = 1_000_000_000


def _series(tvdb_id: int, title: str, *, seasons: list[int], sonarr_id: int = 1) -> dict:
    return {
        "id": sonarr_id,
        "tvdbId": tvdb_id,
        "title": title,
        "year": 2001,
        "runtime": 22,
        "genres": ["Comedy"],
        "monitored": True,
        "qualityProfileId": 4,
        "seasons": [
            {
                "seasonNumber": n,
                "statistics": {
                    "sizeOnDisk": 10 * GB,
                    "totalEpisodeCount": 2,
                    "episodeFileCount": 2,
                },
            }
            for n in seasons
        ],
    }


def _episode(season: int, number: int, *, file_id: int, air: str) -> dict:
    return {
        "id": season * 100 + number,
        "seasonNumber": season,
        "episodeNumber": number,
        "title": f"S{season}E{number}",
        "airDateUtc": air,
        "episodeFileId": file_id,
        "hasFile": True,
    }


def _file(file_id: int, *, size: int, height: int, path: str) -> dict:
    return {
        "id": file_id,
        "path": path,
        "size": size,
        "mediaInfo": {"runTime": "00:22:00", "height": height, "videoCodec": "h264"},
    }


def _persist(pipe: ScanPipeline, series_raw, episodes_raw, files_raw):
    series = [normalize.normalize_sonarr_series(s) for s in series_raw]
    detail = {
        series[0]["tvdb_id"]: {
            "episodes": [normalize.normalize_sonarr_episode(e) for e in episodes_raw],
            "files": [normalize.normalize_sonarr_episode_file(f) for f in files_raw],
        }
    }
    return pipe._persist_sonarr([s for s in series if s], detail)


def test_a_show_lands_with_its_seasons_and_episodes(factory, settings):
    pipe = ScanPipeline(factory, settings)
    counts = _persist(
        pipe,
        [_series(76156, "Scrubs", seasons=[1])],
        [
            _episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z"),
            _episode(1, 2, file_id=502, air="2001-10-09T00:00:00Z"),
        ],
        [
            _file(501, size=700_000_000, height=480, path="/tv/scrubs/s01e01.mkv"),
            _file(502, size=700_000_000, height=480, path="/tv/scrubs/s01e02.mkv"),
        ],
    )
    assert counts["sonarr_shows"] == 1
    with factory() as session:
        show = session.get(Show, 76156)
        assert show is not None and show.runtime == 22 and show.quality_profile_id == 4
        assert len(list(session.scalars(select(Episode)))) == 2
        assert len(list(session.scalars(select(MediaFile)))) == 2


def test_each_season_carries_its_own_air_year(factory, settings):
    """The whole reason seasons are a table. Judged per show, a 2001 comedy would
    have its 2010 season declared SD-native and its HD files called upscales."""
    pipe = ScanPipeline(factory, settings)
    _persist(
        pipe,
        [_series(76156, "Scrubs", seasons=[1, 9])],
        [
            _episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z"),
            _episode(9, 1, file_id=901, air="2009-12-01T00:00:00Z"),
        ],
        [
            _file(501, size=700_000_000, height=480, path="/tv/scrubs/s01e01.mkv"),
            _file(901, size=1_400_000_000, height=1080, path="/tv/scrubs/s09e01.mkv"),
        ],
    )
    with factory() as session:
        years = {
            s.season_number: s.air_year for s in session.scalars(select(Season))
        }
    assert years == {1: 2001, 9: 2009}


def test_a_multi_episode_file_counts_its_disk_once(factory, settings):
    """A single S01E01-E02 file is one file covering two episodes. Sonarr gives
    both episodes the same file id, so counting it per episode would report twice
    the space it actually uses."""
    pipe = ScanPipeline(factory, settings)
    _persist(
        pipe,
        [_series(76156, "Scrubs", seasons=[1])],
        [
            _episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z"),
            _episode(1, 2, file_id=501, air="2001-10-09T00:00:00Z"),
        ],
        [_file(501, size=1_400_000_000, height=480, path="/tv/scrubs/s01e01-e02.mkv")],
    )
    with factory() as session:
        files = list(session.scalars(select(MediaFile)))
        assert len(list(session.scalars(select(Episode)))) == 2
    assert len(files) == 1
    assert sum(f.size or 0 for f in files) == 1_400_000_000


def test_a_series_without_a_tvdb_id_is_dropped():
    """NEGATIVE CONTROL: without it there is nothing to key on and no way to match
    Plex, so the row would be unreachable rather than merely incomplete."""
    assert normalize.normalize_sonarr_series({"id": 1, "title": "Mystery"}) is None


def test_a_rescan_does_not_duplicate_anything(factory, settings):
    pipe = ScanPipeline(factory, settings)
    args = (
        [_series(76156, "Scrubs", seasons=[1])],
        [_episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z")],
        [_file(501, size=700_000_000, height=480, path="/tv/scrubs/s01e01.mkv")],
    )
    _persist(pipe, *args)
    _persist(pipe, *args)
    with factory() as session:
        assert len(list(session.scalars(select(Show)))) == 1
        assert len(list(session.scalars(select(Season)))) == 1
        assert len(list(session.scalars(select(Episode)))) == 1
        assert len(list(session.scalars(select(MediaFile)))) == 1


# ------------------------------------------------------------------ plex TV side


def _plex_episode(rating_key: int, show_key: int, season: int, number: int, parts: list) -> dict:
    raw = {
        "ratingKey": rating_key,
        "grandparentRatingKey": show_key,
        "parentIndex": season,
        "index": number,
        "title": f"S{season}E{number}",
        "Media": [{"height": 1080, "videoCodec": "h264", "Part": parts}],
    }
    return normalize.normalize_plex_episode(raw)


def test_plex_reveals_a_duplicated_episode(factory, settings):
    """Sonarr tracks one file per episode, so a second copy on disk is invisible
    to it. Plex reports every copy, which is what makes the duplicate findable."""
    pipe = ScanPipeline(factory, settings)
    show = normalize.normalize_plex_show(
        {"ratingKey": 3001, "title": "Scrubs", "year": 2001, "Guid": [{"id": "tvdb://76156"}]},
        section_title="TV",
        is_kids=False,
    )
    episode = _plex_episode(
        3101,
        3001,
        1,
        1,
        [
            {"file": "/tv/s01e01.mkv", "size": 1_400_000_000, "duration": 1_320_000},
            {"file": "/tv/s01e01.copy.mkv", "size": 1_400_000_000, "duration": 1_320_000},
        ],
    )
    pipe._persist_plex_tv([show], [episode])
    with factory() as session:
        files = list(session.scalars(select(MediaFile)))
        stored = session.get(Show, 76156)
    assert len(files) == 2
    assert stored is not None and stored.in_plex


def test_an_episode_whose_show_has_no_tvdb_id_is_skipped(factory, settings):
    """NEGATIVE CONTROL: filing it under a guessed show would group unrelated
    files together, which is precisely the mistake duplicate detection must not
    make."""
    pipe = ScanPipeline(factory, settings)
    episode = _plex_episode(
        3101, 9999, 1, 1, [{"file": "/tv/x.mkv", "size": 1_000_000, "duration": 1_320_000}]
    )
    pipe._persist_plex_tv([], [episode])
    with factory() as session:
        assert list(session.scalars(select(Episode))) == []
        assert list(session.scalars(select(MediaFile))) == []


def test_plex_supersedes_sonarr_for_the_same_episode(factory, settings):
    """Both describe the same disk. Keeping both would double it."""
    pipe = ScanPipeline(factory, settings)
    _persist(
        pipe,
        [_series(76156, "Scrubs", seasons=[1])],
        [_episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z")],
        [_file(501, size=700_000_000, height=480, path="/sonarr/s01e01.mkv")],
    )
    show = normalize.normalize_plex_show(
        {"ratingKey": 3001, "title": "Scrubs", "year": 2001, "Guid": [{"id": "tvdb://76156"}]},
        section_title="TV",
        is_kids=False,
    )
    episode = _plex_episode(
        3101, 3001, 1, 1, [{"file": "/plex/s01e01.mkv", "size": 700_000_000, "duration": 1_320_000}]
    )
    pipe._persist_plex_tv([show], [episode])
    with factory() as session:
        files = list(session.scalars(select(MediaFile)))
    assert [f.source for f in files] == ["plex"]
    assert sum(f.size or 0 for f in files) == 700_000_000


# ---------------------------------------------------------------- performance pin


def _count_statements(factory, pipe, episode_count: int) -> tuple[int, int]:
    """(lookups, total) emitted by one ingest of a season of this size."""
    episodes = [
        _episode(1, n, file_id=500 + n, air="2001-10-02T00:00:00Z")
        for n in range(1, episode_count + 1)
    ]
    files = [
        _file(500 + n, size=700_000_000, height=480, path=f"/tv/s01e{n:03d}.mkv")
        for n in range(1, episode_count + 1)
    ]
    series = [_series(76156, "Scrubs", seasons=[1])]

    engine = factory.kw["bind"]
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement.lstrip().split()[0].upper())

    try:
        _persist(pipe, series, episodes, files)
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return statements.count("SELECT"), len(statements)


def test_tv_ingest_does_not_issue_a_lookup_per_episode(factory, settings):
    """The blind spot that produced 2607.15.1, pinned where it actually bites.

    Round trips are free on SQLite and dominate on a hosted database, and the
    defect that release fixed was a SELECT *per row* from ``session.merge``. So
    what has to stay flat is the number of lookups, not the number of writes —
    inserting a hundred new episodes genuinely requires a hundred rows to be
    written, and how the driver batches those varies by dialect.

    Ten episodes and a hundred must cost the same number of lookups. A per-row
    get or merge makes the second number ten times the first.
    """
    small, _ = _count_statements(factory, ScanPipeline(factory, settings), 10)

    with factory() as session:
        session.query(MediaFile).delete()
        session.query(Episode).delete()
        session.query(Season).delete()
        session.query(Show).delete()
        session.commit()

    large, _ = _count_statements(factory, ScanPipeline(factory, settings), 100)
    assert small == large, f"lookups grew from {small} to {large} with the episode count"


def test_a_rescan_costs_a_handful_of_statements(factory, settings):
    """Rescans are the common case — every scheduled scan re-reads the whole
    library — so this is the number that decides whether a big TV library feels
    instant or hung."""
    pipe = ScanPipeline(factory, settings)
    _count_statements(factory, pipe, 100)
    _lookups, total = _count_statements(factory, pipe, 100)
    assert total < 20, f"rescan of 100 episodes emitted {total} statements"
