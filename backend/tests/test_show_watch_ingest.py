"""Episode plays, from Tautulli's history to the columns on `shows`.

This is one of the three axes that decide whether a show needs to be in HD, and
the whole path was uncovered: the existing pipeline double answers episode
history with an empty list, so the episode half of `_phase_tautulli` and all of
`_persist_show_watch` never ran under test.
"""

from __future__ import annotations

from sqlalchemy import event, select

from sift.db.models import Show, WatchHistory
from sift.ingest.pipeline import ScanPipeline
from sift.services.scanner import create_scan_run

from .test_pipeline import TAUTULLI_HISTORY, FakePlex, FakeRadarr, FakeService

# Scrubs is rating key 3001 in the shared Plex double, so these plays land on a
# show the Plex phase has really created rather than one hand-inserted here.
SCRUBS = "3001"


def _play(show_key=SCRUBS, *, date=1700000000, percent=100, resolution="1080"):
    return {
        "grandparent_rating_key": show_key,
        "rating_key": 9999,
        "date": date,
        "percent_complete": percent,
        "video_resolution": resolution,
    }


class EpisodeTautulli(FakeService):
    """Answers episode history, which the shared double deliberately does not."""

    name = "tautulli"
    page_size = 2

    def __init__(self, episodes, *, movies=None):
        super().__init__()
        self.episodes = episodes
        self.movies = TAUTULLI_HISTORY if movies is None else movies
        self.asked_for: list[str] = []

    async def get_history(self, *, media_type: str = "movie"):
        self.asked_for.append(media_type)
        return self.movies if media_type == "movie" else self.episodes

    async def iter_history(self, *, media_type: str = "movie"):
        rows = await self.get_history(media_type=media_type)
        for start in range(0, len(rows), self.page_size):
            yield rows[start : start + self.page_size]


def _pipeline(factory, settings, tautulli):
    return ScanPipeline(
        factory, settings, radarr=FakeRadarr(), plex=FakePlex(), tautulli=tautulli, tmdb=None
    )


async def _scan(factory, settings, tautulli):
    """A full scan, so shows arrive through the real Plex phase rather than by hand."""
    pipe = _pipeline(factory, settings, tautulli)
    await pipe.run(create_scan_run(factory))
    return pipe


async def test_episode_plays_land_on_the_show_they_belong_to(factory, settings):
    """The aggregate is attached by Plex's grandparent rating key, which is the
    only identifier an episode play carries that names its show.
    """
    tautulli = EpisodeTautulli([_play(), _play(date=1700100000), _play(date=1700200000)])
    await _scan(factory, settings, tautulli)

    with factory() as session:
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))

    assert show is not None
    assert show.plays == 3
    assert show.mean_completion == 1.0
    assert show.last_played_at is not None


async def test_history_is_asked_for_both_media_types(factory, settings):
    """Episode history is a separate request, not a filter over the movie sweep.

    `get_history` defaults to `media_type="movie"`, so a caller that forgot the
    argument would silently aggregate film plays into the show columns.
    """
    tautulli = EpisodeTautulli([_play()])
    await _scan(factory, settings, tautulli)

    assert "movie" in tautulli.asked_for
    assert "episode" in tautulli.asked_for


async def test_plays_for_a_show_plex_does_not_have_are_dropped(factory, settings):
    """NEGATIVE CONTROL: an unmatched rating key writes nothing at all.

    Tautulli's history outlives the library — a show removed from Plex still has
    plays on record. Those must not be attached to some other show, and must not
    raise: history is evidence, and evidence about something that is gone is
    simply not usable.
    """
    tautulli = EpisodeTautulli([_play(show_key="9999"), _play(show_key="8888")])
    await _scan(factory, settings, tautulli)

    with factory() as session:
        shows = list(session.scalars(select(Show)))

    assert shows, "the Plex phase should still have created Scrubs"
    assert all(s.plays == 0 for s in shows)
    assert all(s.last_played_at is None for s in shows)


async def test_an_episode_play_never_becomes_a_film_watch_row(factory, settings):
    """NEGATIVE CONTROL: `WatchHistory` is FK'd to `movies.tmdb_id` and cannot
    hold TV rows. If the episode sweep were folded through the movie normalizer,
    an episode's rating key would be read as a film's and either land on the
    wrong film or fail the constraint.
    """
    tautulli = EpisodeTautulli([_play(), _play(date=1700100000)], movies=[])
    await _scan(factory, settings, tautulli)

    with factory() as session:
        assert list(session.scalars(select(WatchHistory))) == []
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))

    assert show is not None and show.plays == 2


async def test_the_recorded_height_is_the_typical_one_not_the_best(factory, settings):
    """One 4K play on a borrowed television must not argue that the whole show
    needs a 4K master. The column stores the median delivered height.
    """
    plays = [_play(resolution="720", date=1700000000 + i) for i in range(5)]
    plays.append(_play(resolution="4k", date=1700900000))
    tautulli = EpisodeTautulli(plays)
    await _scan(factory, settings, tautulli)

    with factory() as session:
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))

    assert show is not None
    assert show.typical_stream_height == 720


async def test_a_play_with_no_reported_resolution_leaves_the_height_unknown(factory, settings):
    """NEGATIVE CONTROL for the height: absent is not zero and not SD.

    Tautulli reports nothing for some plays. Defaulting those to 480 would tell
    the suitability rules a show is watched in standard definition when nothing
    of the sort is known, and a downgrade is the irreversible direction.
    """
    tautulli = EpisodeTautulli([_play(resolution=""), _play(resolution=None, date=1700100000)])
    await _scan(factory, settings, tautulli)

    with factory() as session:
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))

    assert show is not None
    assert show.plays == 2  # the play still counts
    assert show.typical_stream_height is None  # the height does not


async def test_completion_averages_only_the_plays_that_reported_it(factory, settings):
    """A play with no percentage is not a play at 0%. Counting it as one would
    drag the mean down and read as a show nobody finishes.
    """
    tautulli = EpisodeTautulli([
        _play(percent=100),
        _play(percent=50, date=1700100000),
        _play(percent=None, date=1700200000),
    ])
    await _scan(factory, settings, tautulli)

    with factory() as session:
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))

    assert show is not None
    assert show.plays == 3
    assert show.mean_completion == 0.75  # (1.0 + 0.5) / 2, not / 3


async def test_attaching_watch_data_does_not_query_per_show(factory, settings):
    """Regression pin, matching the one on the Plex phase. `_persist_show_watch`
    preloads every show with a rating key in one statement and matches in memory.

    A lookup per show is invisible on SQLite, where a round trip is free, and is
    the difference between a phase that finishes and one that looks hung on a
    hosted database. Bounded as a constant handful rather than a per-show budget,
    so it pins the shape without being brittle.
    """
    plays = [_play(show_key=str(9000 + i), date=1700000000 + i) for i in range(200)]
    plays += [_play(date=1700500000)]
    pipe = await _scan(factory, settings, EpisodeTautulli(plays))  # populate

    engine = factory.kw["bind"]
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _tick(*_a, **_kw):
        statements["n"] += 1

    try:
        from sift.ingest import normalize

        rows = [normalize.normalize_tautulli_episode_row(p) for p in plays]
        aggregates = normalize.aggregate_show_watch([r for r in rows if r is not None])
        pipe._persist_show_watch(list(aggregates.values()))
    finally:
        event.remove(engine, "before_cursor_execute", _tick)

    assert statements["n"] < 10, f"{statements['n']} statements for 201 shows — per-show lookups?"


async def test_no_episode_history_writes_nothing_and_does_not_fail(factory, settings):
    """NEGATIVE CONTROL: an empty sweep is the ordinary case for a library with no
    TV, and it must short-circuit rather than open a session to write nothing.
    """
    pipe = await _scan(factory, settings, EpisodeTautulli([]))

    assert pipe._persist_show_watch([]) == {"show_watch": 0}
    with factory() as session:
        show = session.scalar(select(Show).where(Show.plex_rating_key == SCRUBS))
    assert show is not None and show.plays == 0
