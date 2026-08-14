"""TV ingest: shows, seasons, episodes, and the files behind them.

The season is the grain that matters. A show's first year is the wrong ceiling
for its later seasons — Scrubs began in 2001 on SD video and ended in HD — so
these pin that each season carries its own air year rather than inheriting one.
"""

from __future__ import annotations

from sqlalchemy import event, func, select

from sift.db.models import Episode, MediaFile, Season, Show
from sift.ingest import normalize
from sift.ingest import pipeline as pipeline_mod
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


# --------------------------------------------------------------- streaming Sonarr


class FakeSonarr:
    """Sonarr as the phase actually uses it: one catalog call, then two calls per
    show. ``probe`` runs after each show is served, which is the only vantage
    point that can tell writing-as-you-go from writing-at-the-end."""

    def __init__(self, series, episodes_by_id, files_by_id, probe=None):
        self.series = series
        self.episodes_by_id = episodes_by_id
        self.files_by_id = files_by_id
        self.probe = probe
        self.served = 0

    async def get_series(self):
        return self.series

    async def get_episodes(self, sonarr_id):
        return self.episodes_by_id.get(sonarr_id, [])

    async def get_episode_files(self, sonarr_id):
        self.served += 1
        if self.probe is not None:
            self.probe()
        return self.files_by_id.get(sonarr_id, [])


def _library(show_count: int, *, episodes_each: int = 4):
    """A library of distinct shows, each with one season of episodes and files."""
    series, episodes_by_id, files_by_id = [], {}, {}
    for i in range(show_count):
        sonarr_id = i + 1
        tvdb_id = 70000 + i
        series.append(_series(tvdb_id, f"Show {i}", seasons=[1], sonarr_id=sonarr_id))
        base = sonarr_id * 1000
        episodes_by_id[sonarr_id] = [
            _episode(1, n, file_id=base + n, air="2001-10-02T00:00:00Z")
            for n in range(1, episodes_each + 1)
        ]
        files_by_id[sonarr_id] = [
            _file(base + n, size=700_000_000, height=480, path=f"/tv/{tvdb_id}/s01e{n:02d}.mkv")
            for n in range(1, episodes_each + 1)
        ]
    return series, episodes_by_id, files_by_id


async def test_sonarr_is_written_as_it_is_read_and_every_batch_survives(
    factory, settings, monkeypatch
):
    """The Plex phase's failure, one phase later.

    Sonarr is the heaviest read in the scan — two calls per show, each returning
    every episode and every file it knows about — and it was accumulating all of
    it to write once at the end. That is the shape that got the Plex phase killed
    for memory, so it has to stream too; and once it streams, the stale sweep can
    no longer be decided from a single batch without deleting the batches either
    side of it.
    """
    monkeypatch.setattr(pipeline_mod, "SERIES_BATCH", 3)
    shows_during: list[int] = []

    def probe() -> None:
        with factory() as session:
            shows_during.append(session.scalar(select(func.count()).select_from(Show)))

    series, episodes_by_id, files_by_id = _library(10)
    sonarr = FakeSonarr(series, episodes_by_id, files_by_id, probe=probe)
    counts = await ScanPipeline(factory, settings, sonarr=sonarr)._phase_sonarr()

    assert counts["sonarr_shows"] == 10
    assert counts["sonarr_episodes"] == 40
    # Shows were on disk well before the last one was read.
    assert shows_during[-2] > 0

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Show)) == 10
        assert session.scalar(select(func.count()).select_from(Episode)) == 40
        assert session.scalar(
            select(func.count()).select_from(MediaFile).where(MediaFile.source == "sonarr")
        ) == 40


async def test_a_sonarr_library_inside_one_batch_is_unchanged(factory, settings, monkeypatch):
    """NEGATIVE CONTROL. With the batch bigger than the library there is one
    write, so batching cannot be what produced the rows above, and the totals
    must match anyway."""
    monkeypatch.setattr(pipeline_mod, "SERIES_BATCH", 1000)
    series, episodes_by_id, files_by_id = _library(10)
    sonarr = FakeSonarr(series, episodes_by_id, files_by_id)
    counts = await ScanPipeline(factory, settings, sonarr=sonarr)._phase_sonarr()
    assert counts["sonarr_shows"] == 10
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Episode)) == 40


async def test_a_batched_sonarr_rescan_drops_only_what_sonarr_dropped(
    factory, settings, monkeypatch
):
    """The sweep still has to bite, and only where it should.

    A file Sonarr stops reporting is gone and must leave. Every other file — most
    of them written in a different batch from the one that triggers the sweep —
    must stay. A sweep decided per batch passes the first half of that and fails
    the second, keeping only the last batch of a library.
    """
    monkeypatch.setattr(pipeline_mod, "SERIES_BATCH", 3)
    series, episodes_by_id, files_by_id = _library(10)

    async def _scan() -> None:
        await ScanPipeline(
            factory, settings, sonarr=FakeSonarr(series, episodes_by_id, files_by_id)
        )._phase_sonarr()

    await _scan()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MediaFile)) == 40

    # The very first show loses an episode file — an early batch, so a sweep that
    # only ever sees the final batch would miss it entirely.
    gone = files_by_id[1].pop()["path"]
    episodes_by_id[1].pop()
    await _scan()

    with factory() as session:
        paths = set(session.scalars(select(MediaFile.path)).all())
        assert gone not in paths
        assert len(paths) == 39


async def test_the_sonarr_phase_reports_progress_while_it_runs(factory, settings, monkeypatch):
    """Two HTTP calls per show against a remote Sonarr is minutes of silence on a
    real library. A phase that says nothing until it finishes is the thing that
    made the last stall take a round trip to diagnose."""
    monkeypatch.setattr(pipeline_mod, "SERIES_BATCH", 3)
    seen: list[str] = []

    async def progress_cb(update):
        if update.phase == "sonarr" and update.status == "running" and update.message:
            seen.append(update.message)

    series, episodes_by_id, files_by_id = _library(10)
    pipe = ScanPipeline(
        factory,
        settings,
        sonarr=FakeSonarr(series, episodes_by_id, files_by_id),
        progress_cb=progress_cb,
    )
    pipe._progress_at = (1, "sonarr", 3)
    await pipe._phase_sonarr()

    assert len(seen) >= 3
    assert any("shows" in message for message in seen)


def test_the_catalog_preloads_name_the_shows_they_want(factory, settings):
    """Scoping, pinned structurally because the cost it prevents is invisible here.

    Reading every season and every episode in the database was free when this ran
    once per scan. Batched, it re-hydrates both whole tables for every batch — on
    a library of 30,000 episodes that is hundreds of thousands of ORM objects
    built and thrown away, and a file-backed SQLite test cannot feel any of it.
    So the pin is on the shape of the query rather than the clock: every read of
    seasons or episodes must carry a filter.
    """
    pipe = ScanPipeline(factory, settings)
    engine = factory.kw["bind"]
    unfiltered: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        text = " ".join(statement.split())
        if text.upper().startswith("SELECT") and " WHERE " not in text.upper():
            if " FROM seasons" in text or " FROM episodes" in text:
                unfiltered.append(text)

    try:
        _persist(
            pipe,
            [_series(76156, "Scrubs", seasons=[1])],
            [_episode(1, 1, file_id=501, air="2001-10-02T00:00:00Z")],
            [_file(501, size=700_000_000, height=480, path="/tv/scrubs/s01e01.mkv")],
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert not unfiltered, f"unscoped catalog read: {unfiltered}"


def test_the_episode_batch_write_never_reads_a_whole_table(factory, settings):
    """The stall that survived three streaming fixes.

    Episodes are written in `EPISODE_BATCH` chunks. `_persist_plex_episodes` used
    to preload every show, every season and every episode in the database on each
    call — so batch 15 of a 30,000-episode library re-hydrated 28,000 rows to write
    2,000, and the scan got slower the further it went. That is quadratic work
    introduced by the very batching that fixed the memory problem, and it reads to
    a user as a progress bar that climbs and then stops.

    Pinned structurally rather than by the clock: on SQLite the rows are local and
    cheap, which is exactly why this survived. Against hosted Postgres every one of
    them crosses the network.
    """
    from sift.ingest.pipeline import ScanPipeline

    with factory() as session:
        session.add(Show(tvdb_id=4242, title="Scrubs", plex_rating_key="rk1", in_plex=True))
        session.commit()

    pipe = ScanPipeline(factory, settings)
    engine = factory.kw["bind"]
    unscoped: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        text = " ".join(statement.split())
        if not text.upper().startswith("SELECT") or " WHERE " in text.upper():
            return
        if any(f" FROM {table}" in text for table in ("shows", "seasons", "episodes")):
            unscoped.append(text)

    batch = [
        {
            "show_rating_key": "rk1", "season_number": 1, "episode_number": n,
            "title": f"E{n}", "plex_rating_key": f"rk1-1-{n}",
            "media_files": [{
                "path": f"/tv/s01e{n:03d}.mkv", "size": 1_000_000_000,
                "duration_ms": 1_320_000, "width": 1920, "height": 1080,
                "resolution": "1080p", "video_codec": "h264", "container": "mkv",
                "part_group": None, "rating_key": None,
            }],
        }
        for n in range(1, 6)
    ]
    try:
        pipe._persist_plex_episodes(batch)
        pipe._persist_plex_episodes(batch)  # a second batch is where the cost showed
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert not unscoped, f"whole-table read inside a per-batch write: {unscoped}"


def test_the_show_write_reads_only_the_shows_it_was_given(factory, settings):
    """The last unscoped preload in the ingest path.

    `_persist_plex_shows` runs once per TV library section rather than per batch,
    so reading the whole table was linear rather than quadratic — but a library
    with several sections still re-read every show for each one. Pinned with the
    same structural check as the batch write above, because the rule is easier to
    keep than to remember which functions are allowed to break it.
    """
    from sift.ingest.pipeline import ScanPipeline

    with factory() as session:
        for n in range(5):
            session.add(Show(tvdb_id=8000 + n, title=f"Existing {n}", in_plex=True))
        session.commit()

    pipe = ScanPipeline(factory, settings)
    engine = factory.kw["bind"]
    unscoped: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        text = " ".join(statement.split())
        if text.upper().startswith("SELECT") and " FROM shows" in text and " WHERE " not in text:
            unscoped.append(text)

    try:
        pipe._persist_plex_shows(
            [
                {
                    "tvdb_id": 8000,
                    "title": "Existing 0",
                    "year": 2001,
                    "plex_rating_key": "rk-8000",
                    "library_section": "TV",
                    "is_kids": False,
                    "tmdb_id": None,
                }
            ]
        )
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert not unscoped, f"whole-table read in the show write: {unscoped}"
