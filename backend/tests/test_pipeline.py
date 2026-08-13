"""End-to-end ingestion pipeline: population, kids guard, resumability."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from sift.clients.base import HealthStatus
from sift.db.models import Collection, Movie, ScanStatus, WatchHistory
from sift.ingest import pipeline as pipeline_mod
from sift.ingest.pipeline import ScanPipeline
from sift.services.scanner import create_scan_run

# --------------------------------------------------------------------- fixtures data

RADARR_MOVIES = [
    {"id": 1, "tmdbId": 603, "title": "The Matrix", "year": 1999, "monitored": True,
     "hasFile": True, "genres": ["Action"], "ratings": {"tmdb": {"value": 8.2, "votes": 20000}}},
    {"id": 2, "tmdbId": 604, "title": "The Matrix Reloaded", "year": 2003, "monitored": True,
     "hasFile": False, "genres": ["Action"]},
    {"id": 3, "tmdbId": 862, "title": "Toy Story", "year": 1995, "monitored": True,
     "hasFile": True, "genres": ["Animation"]},
]
RADARR_COLLECTIONS = [
    {"tmdbId": 2344, "title": "The Matrix Collection", "movies": [
        {"tmdbId": 603, "title": "The Matrix", "year": 1999, "monitored": True, "id": 1},
        {"tmdbId": 605, "title": "The Matrix Revolutions", "year": 2003, "monitored": False},
    ]},
]
PLEX_SECTIONS = [
    {"key": "1", "type": "movie", "title": "Movies"},
    {"key": "2", "type": "movie", "title": "Kids Movies"},
    {"key": "3", "type": "show", "title": "TV"},
]
PLEX_ITEMS = {
    "1": [
        {"ratingKey": 1001, "title": "The Matrix", "year": 1999, "Guid": [{"id": "tmdb://603"}]},
        {"ratingKey": 1002, "title": "Plex Only", "year": 2010, "Guid": [{"id": "tmdb://11"}]},
    ],
    "2": [
        {"ratingKey": 2001, "title": "Toy Story", "year": 1995, "Guid": [{"id": "tmdb://862"}]},
    ],
}
# The TV section, keyed by (section, Plex item type). Shows carry the TVDB guid
# that ties them to Sonarr; episodes carry the files.
PLEX_TV = {
    ("3", 2): [
        {"ratingKey": 3001, "title": "Scrubs", "year": 2001, "Guid": [{"id": "tvdb://76156"}]},
    ],
    ("3", 4): [
        {
            "ratingKey": 3101,
            "grandparentRatingKey": 3001,
            "parentIndex": 1,
            "index": 1,
            "title": "My First Day",
            "Media": [
                {
                    "height": 480,
                    "videoCodec": "h264",
                    "Part": [
                        {
                            "file": "/tv/scrubs/s01e01.mkv",
                            "size": 700_000_000,
                            "duration": 1_320_000,
                        }
                    ],
                }
            ],
        },
    ],
}
TAUTULLI_HISTORY = [
    {"rating_key": 1001, "user": "Dad", "date": 1700000000, "percent_complete": 100},
    {"rating_key": 1001, "user": "Dad", "date": 1700100000, "percent_complete": 100},
    {"rating_key": 2001, "user": "Kiddo", "date": 1700000000, "percent_complete": 90},
]


class FakeService:
    """Every real client answers a preflight probe, so the doubles must too.
    ``reachable=False`` stands in for a service that's configured but down."""

    name = "fake"

    def __init__(self, *, reachable: bool = True):
        self.reachable = reachable
        self.probed = False

    async def health(self):
        self.probed = True
        return HealthStatus(self.name, self.reachable, "" if self.reachable else "refused")


class FakeRadarr(FakeService):
    name = "radarr"

    async def get_movies(self):
        return RADARR_MOVIES

    async def get_collections(self):
        return RADARR_COLLECTIONS


class FakePlex(FakeService):
    name = "plex"

    # Deliberately tiny so any sweep that matters spans several pages — the
    # streaming path is only worth having if it is exercised in more than one
    # batch, and a fake that returns everything at once would never prove it.
    page_size = 2

    async def get_sections(self):
        return PLEX_SECTIONS

    def _items(self, key, item_type):
        if item_type == 1:
            return PLEX_ITEMS.get(str(key), [])
        return PLEX_TV.get((str(key), item_type), [])

    async def iter_section_items(self, key, *, item_type=1):
        items = self._items(key, item_type)
        for start in range(0, len(items), self.page_size):
            yield items[start : start + self.page_size]

    async def get_section_items(self, key, *, item_type=1):
        return self._items(key, item_type)


class FakeTautulli(FakeService):
    name = "tautulli"

    def __init__(self, *, fail: bool = False, reachable: bool = True):
        super().__init__(reachable=reachable)
        self.fail = fail

    async def get_history(self, *, media_type: str = "movie"):
        if self.fail:
            raise RuntimeError("tautulli dropped mid-scan")
        return TAUTULLI_HISTORY


class HangingTautulli(FakeTautulli):
    """Configured, accepts the connection, never answers — the case no try/except
    can catch and only a timeout can."""

    async def health(self):
        self.probed = True
        await asyncio.sleep(3600)
        raise AssertionError("unreachable: the preflight timeout should have fired")


def _configure_kids(settings):
    settings.plex.kids_sections = ["Kids Movies"]
    settings.tautulli.kids_accounts = ["Kiddo"]
    return settings


def _pipeline(factory, settings, *, tautulli):
    return ScanPipeline(
        factory, settings, radarr=FakeRadarr(), plex=FakePlex(), tautulli=tautulli, tmdb=None
    )


async def test_full_scan_populates_snapshot_and_kids_guard(factory, settings):
    _configure_kids(settings)
    scan_id = create_scan_run(factory)
    run = await _pipeline(factory, settings, tautulli=FakeTautulli()).run(scan_id)
    assert run.status == ScanStatus.COMPLETED

    with factory() as session:
        # 3 radarr movies + 1 plex-only stub.
        assert session.scalar(select(func.count()).select_from(Movie)) == 4
        matrix = session.get(Movie, 603)
        assert matrix.plex_rating_key == "1001" and matrix.is_kids is False
        assert matrix.in_plex is True  # in a Plex movie section
        toy = session.get(Movie, 862)
        assert toy.is_kids is True  # kids section guard applied
        plex_only = session.get(Movie, 11)
        assert plex_only is not None and plex_only.in_plex is True
        # In the Radarr catalog but NOT in Plex → not part of the library.
        reloaded = session.get(Movie, 604)
        assert reloaded is not None and reloaded.in_plex is False

        # "Owned"/library membership is Plex presence: 603, 862, 11 (not 604).
        in_plex_count = session.scalar(
            select(func.count()).select_from(Movie).where(Movie.in_plex.is_(True))
        )
        assert in_plex_count == 3

        watches = session.scalars(select(WatchHistory)).all()
        assert len(watches) == 2
        dad = session.scalars(
            select(WatchHistory).where(WatchHistory.movie_id == 603)
        ).first()
        assert dad.plays == 2 and dad.plex_user == "Dad"
        kiddo = session.scalars(
            select(WatchHistory).where(WatchHistory.movie_id == 862)
        ).first()
        assert kiddo.is_kids_account is True

        coll = session.get(Collection, 2344)
        assert coll.total_count == 2 and coll.owned_count == 1


async def test_scan_is_idempotent(factory, settings):
    _configure_kids(settings)
    for _ in range(2):
        scan_id = create_scan_run(factory)
        await _pipeline(factory, settings, tautulli=FakeTautulli()).run(scan_id)
    with factory() as session:
        # Re-running must not duplicate movies or watch rows.
        assert session.scalar(select(func.count()).select_from(Movie)) == 4
        assert session.scalar(select(func.count()).select_from(WatchHistory)) == 2


async def test_interrupted_scan_resumes_to_same_result(factory, settings):
    _configure_kids(settings)

    # 1) Interrupt during the tautulli phase.
    scan_id = create_scan_run(factory)
    with pytest.raises(RuntimeError):
        await _pipeline(factory, settings, tautulli=FakeTautulli(fail=True)).run(scan_id)

    with factory() as session:
        from sift.db.models import ScanRun

        run = session.get(ScanRun, scan_id)
        assert run.status == ScanStatus.INTERRUPTED
        assert run.checkpoints["radarr"]["status"] == "done"
        assert run.checkpoints["plex"]["status"] == "done"
        assert "tautulli" not in run.checkpoints
        # Movies were written before the interruption; watch history was not.
        assert session.scalar(select(func.count()).select_from(Movie)) == 4
        assert session.scalar(select(func.count()).select_from(WatchHistory)) == 0

    # 2) Resume with a healthy client.
    resumed = await _pipeline(factory, settings, tautulli=FakeTautulli()).run(scan_id, resume=True)
    assert resumed.status == ScanStatus.COMPLETED

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Movie)) == 4
        assert session.scalar(select(func.count()).select_from(WatchHistory)) == 2


# ------------------------------------------------------------------------ preflight


async def test_unreachable_service_is_skipped_not_fatal(factory, settings):
    """The reported bug: a saved-but-dead Tautulli took the whole scan down with it,
    so a perfectly good Radarr never got read."""
    _configure_kids(settings)
    dead = FakeTautulli(reachable=False)
    scan_id = create_scan_run(factory)
    run = await _pipeline(factory, settings, tautulli=dead).run(scan_id)

    assert run.status == ScanStatus.COMPLETED  # the scan still finishes
    assert run.stats["services_skipped"] == 1
    assert run.stats["services_ready"] == 2  # radarr + plex carried on
    with factory() as session:
        # Radarr and Plex were ingested normally...
        assert session.scalar(select(func.count()).select_from(Movie)) == 4
        # ...and the dead service simply contributed nothing.
        assert session.scalar(select(func.count()).select_from(WatchHistory)) == 0


async def test_a_service_that_never_answers_is_bounded_by_the_timeout(factory, settings):
    """A refused connection fails fast on its own; a black hole doesn't. Only the
    timeout distinguishes 'slow' from 'never', so it has to be the thing that fires."""
    _configure_kids(settings)
    monkeypatched = 0.05  # keep the test quick; the real bound is 15s
    original = pipeline_mod.PREFLIGHT_TIMEOUT_SECONDS
    pipeline_mod.PREFLIGHT_TIMEOUT_SECONDS = monkeypatched
    try:
        scan_id = create_scan_run(factory)
        run = await _pipeline(factory, settings, tautulli=HangingTautulli()).run(scan_id)
    finally:
        pipeline_mod.PREFLIGHT_TIMEOUT_SECONDS = original

    assert run.status == ScanStatus.COMPLETED
    assert run.stats["services_skipped"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Movie)) == 4


async def test_reachable_services_are_all_kept(factory, settings):
    """Negative control: with everything answering, preflight must drop nothing."""
    _configure_kids(settings)
    tautulli = FakeTautulli()
    scan_id = create_scan_run(factory)
    run = await _pipeline(factory, settings, tautulli=tautulli).run(scan_id)

    assert tautulli.probed is True  # it really was probed...
    assert run.stats["services_skipped"] == 0  # ...and kept
    assert run.stats["services_ready"] == 3
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WatchHistory)) == 2


async def test_midscan_failure_still_interrupts_and_resumes(factory, settings):
    """Preflight guards against 'down when we started', not 'died halfway'. A service
    that passes the probe and then fails must still interrupt the run so the resume
    machinery can pick it up — otherwise the guard would mask real breakage."""
    _configure_kids(settings)
    scan_id = create_scan_run(factory)
    with pytest.raises(RuntimeError):
        await _pipeline(factory, settings, tautulli=FakeTautulli(fail=True)).run(scan_id)
    with factory() as session:
        from sift.db.models import ScanRun

        assert session.get(ScanRun, scan_id).status == ScanStatus.INTERRUPTED


# ------------------------------------------------------------------ streaming TV

def _many_episodes(count: int) -> list[dict]:
    """One show's worth of episodes, sized to span several write batches."""
    return [
        {
            "ratingKey": 4000 + n,
            "grandparentRatingKey": 3001,
            "parentIndex": 1 + n // 10,
            "index": 1 + n % 10,
            "title": f"Episode {n}",
            "Media": [
                {
                    "height": 1080,
                    "videoCodec": "h264",
                    "Part": [
                        {
                            "file": f"/tv/scrubs/s{1 + n // 10:02d}e{1 + n % 10:02d}.mkv",
                            "size": 1_400_000_000,
                            "duration": 1_320_000,
                        }
                    ],
                }
            ],
        }
        for n in range(count)
    ]


class StreamingPlex(FakePlex):
    """A TV section large enough to page, with a hook between pages.

    ``probe`` runs after each page is handed over, which is the only moment that
    can tell streaming apart from accumulation: mid-sweep, either the database
    already holds episodes or it doesn't.
    """

    page_size = 5

    def __init__(self, episodes, probe=None, **kwargs):
        super().__init__(**kwargs)
        self.episodes = episodes
        self.probe = probe
        self.pages = 0

    def _items(self, key, item_type):
        if (str(key), item_type) == ("3", 4):
            return self.episodes
        return super()._items(key, item_type)

    async def iter_section_items(self, key, *, item_type=1):
        async for batch in super().iter_section_items(key, item_type=item_type):
            yield batch
            if (str(key), item_type) == ("3", 4):
                self.pages += 1
                if self.probe is not None:
                    self.probe()


async def test_episodes_are_written_as_they_arrive_and_every_batch_survives(
    factory, settings, monkeypatch
):
    """A big TV sweep must reach the database in pieces, and keep all of them.

    Two failures hide here and only show up together. Holding every episode until
    the sweep ends is what got a real scan killed for memory — the run then stays
    marked running forever, which reads to the user as a bar frozen at the same
    percentage. But writing in batches introduces the opposite hazard: the stale
    -copy sweep that keeps a rescan honest will, if it is not scoped to the
    episodes in hand, treat every previous batch as vanished and delete it. Then
    a 30,000-episode library persists as the last few hundred.
    """
    from sift.db.models import Episode, MediaFile

    monkeypatch.setattr(pipeline_mod, "EPISODE_BATCH", 4)
    total = 23  # not a multiple of the batch, so the final partial write counts
    counts_during: list[int] = []

    def probe() -> None:
        with factory() as session:
            counts_during.append(session.scalar(select(func.count()).select_from(Episode)))

    plex = StreamingPlex(_many_episodes(total), probe=probe)
    scan_id = create_scan_run(factory)
    pipeline = ScanPipeline(
        factory, _configure_kids(settings), radarr=FakeRadarr(), plex=plex,
        tautulli=FakeTautulli(), tmdb=None,
    )
    run = await pipeline.run(scan_id)
    assert run.status == ScanStatus.COMPLETED

    assert plex.pages == 5  # 23 episodes at 5 per page — it really did stream
    # Rows existed before the last page was read: the proof of incremental writes.
    assert counts_during[-2] > 0

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Episode)) == total
        files = session.scalar(
            select(func.count()).select_from(MediaFile).where(MediaFile.episode_id.isnot(None))
        )
        assert files == total


async def test_a_tv_sweep_that_fits_in_one_batch_is_unchanged(factory, settings, monkeypatch):
    """NEGATIVE CONTROL. With the batch larger than the library there is exactly
    one write, so batching cannot be what produced the rows above — and the same
    counts must still come out. A stale sweep broken in the other direction
    (scoped so tightly it never deletes) would pass this and fail the rescan pin
    below, which is why both exist."""
    from sift.db.models import Episode

    monkeypatch.setattr(pipeline_mod, "EPISODE_BATCH", 10_000)
    plex = StreamingPlex(_many_episodes(23))
    plex.page_size = 1000
    scan_id = create_scan_run(factory)
    pipeline = ScanPipeline(
        factory, _configure_kids(settings), radarr=FakeRadarr(), plex=plex,
        tautulli=FakeTautulli(), tmdb=None,
    )
    await pipeline.run(scan_id)
    assert plex.pages == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Episode)) == 23


async def test_a_batched_rescan_still_drops_files_that_are_gone(factory, settings, monkeypatch):
    """Both halves of the stale sweep, because each one breaks the other.

    The duplicate copy here sits at the far end of the sweep, so the two copies of
    episode one land in different write batches — the ordinary case in a real
    library, where Plex reports copies wherever it finds them. Any delete rule
    evaluated per batch reads the first copy as missing when the second arrives
    and removes it, destroying the duplicate the feature exists to find in the act
    of recording it. That is the first assertion.

    Deleting nothing at all passes that and fails the second: a copy removed on
    disk has to leave, or Sift keeps recommending the deletion of a file that is
    already gone.
    """
    from sift.db.models import MediaFile

    monkeypatch.setattr(pipeline_mod, "EPISODE_BATCH", 4)
    episodes = _many_episodes(23)
    # A second copy of episode one, arriving batches later than the first.
    surplus = dict(episodes[0])
    surplus["ratingKey"] = 9999
    surplus["Media"] = [
        {
            "height": 480,
            "videoCodec": "h264",
            "Part": [{"file": "/tv/scrubs/s01e01.dup.mkv", "size": 400_000_000,
                      "duration": 1_320_000}],
        }
    ]

    async def _scan(items):
        plex = StreamingPlex(items)
        scan_id = create_scan_run(factory)
        await ScanPipeline(
            factory, _configure_kids(settings), radarr=FakeRadarr(), plex=plex,
            tautulli=FakeTautulli(), tmdb=None,
        ).run(scan_id)

    await _scan([*episodes, surplus])
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(MediaFile).where(MediaFile.episode_id.isnot(None))
        ) == 24

    await _scan(episodes)  # the surplus copy has been deleted on disk
    with factory() as session:
        paths = set(
            session.scalars(select(MediaFile.path).where(MediaFile.episode_id.isnot(None))).all()
        )
        assert "/tv/scrubs/s01e01.dup.mkv" not in paths
        assert len(paths) == 23


async def test_a_long_phase_reports_progress_while_it_runs(factory, settings, monkeypatch):
    """A phase that emits only 'running' and then 'done' is indistinguishable from
    a dead process for as long as it takes. The Plex phase is the long one, so it
    has to say something in between."""
    monkeypatch.setattr(pipeline_mod, "EPISODE_BATCH", 4)
    seen: list[tuple[str, str, str]] = []

    async def progress_cb(update):
        seen.append((update.phase, update.status, update.message))

    plex = StreamingPlex(_many_episodes(23))
    scan_id = create_scan_run(factory)
    await ScanPipeline(
        factory, _configure_kids(settings), radarr=FakeRadarr(), plex=plex,
        tautulli=FakeTautulli(), tmdb=None, progress_cb=progress_cb,
    ).run(scan_id)

    mid = [m for phase, status, m in seen if phase == "plex" and status == "running" and m]
    assert len(mid) >= 2
    assert any("episodes" in m for m in mid)
