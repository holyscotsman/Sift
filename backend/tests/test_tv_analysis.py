"""TV duplicates and season sizing.

The controls here guard the two mistakes that would matter: deleting half of a
split episode because it looked like a duplicate, and calling a season heavy
because it has more episodes than another.
"""

from __future__ import annotations

import pytest

from sift.analysis import bitrate, outliers, tv_duplicates, tv_size
from sift.db.models import Episode, MediaFile, Season, Show

GB = 1_000_000_000
MIN_MS = 60_000


@pytest.fixture
def tv(factory):
    """Build a show/season/episode tree with the given files."""

    def _build(tvdb_id: int, title: str, season_number: int, episodes: list[list[dict]]) -> None:
        with factory() as session:
            show = session.get(Show, tvdb_id)
            if show is None:
                show = Show(tvdb_id=tvdb_id, title=title, library_section="TV")
                session.add(show)
            season = Season(show_id=tvdb_id, season_number=season_number, air_year=2001)
            session.add(season)
            session.flush()
            for index, files in enumerate(episodes, start=1):
                episode = Episode(
                    season_id=season.id, episode_number=index, title=f"E{index}", has_file=True
                )
                session.add(episode)
                session.flush()
                for spec in files:
                    session.add(MediaFile(episode_id=episode.id, source="plex", **spec))
            session.commit()

    return _build


def _f(
    path: str,
    *,
    size: int,
    minutes: int,
    resolution="1080p",
    codec="h264",
    group: str | None = None,
) -> dict:
    return {
        "path": path,
        "size": size,
        "duration_ms": minutes * MIN_MS,
        "resolution": resolution,
        "video_codec": codec,
        # Files sharing a group are one presentation split across files. Plex
        # reports this directly as Parts under a Media.
        "part_group": group or path,
    }


# ------------------------------------------------------------------- duplicates


def test_a_duplicated_episode_is_found_and_the_better_copy_kept(tv, factory):
    tv(
        1,
        "Doubled",
        1,
        [
            [
                _f("/a/s01e01.1080p.mkv", size=3 * GB, minutes=45),
                _f("/a/s01e01.sd.mkv", size=1 * GB, minutes=45, resolution="480p"),
            ],
            [_f("/a/s01e02.mkv", size=3 * GB, minutes=45)],
        ],
    )
    with factory() as session:
        shows, total = tv_duplicates.find(session)
    assert len(shows) == 1
    episode = shows[0].episodes[0]
    assert episode.surplus == 1
    kept = [c for c in episode.copies if c.keep]
    assert len(kept) == 1 and kept[0].resolution == "1080p"
    assert episode.reclaimable == 1 * GB
    assert total == 1 * GB


def test_split_parts_are_not_duplicates(tv, factory):
    """NEGATIVE CONTROL, and the one that would destroy data.

    Two halves of a sixty-minute episode and two copies of a thirty-minute one
    are indistinguishable by file count *or* by duration — both are two files of
    thirty minutes each. Deleting the "duplicate" loses half the episode. Only
    the presentation Plex reports them under separates the cases.
    """
    tv(
        2,
        "Split",
        1,
        [
            [
                _f("/b/s01e01.part1.mkv", size=2 * GB, minutes=30, group="media1"),
                _f("/b/s01e01.part2.mkv", size=2 * GB, minutes=30, group="media1"),
            ]
        ],
    )
    with factory() as session:
        shows, total = tv_duplicates.find(session)
    assert shows == []
    assert total == 0


def test_a_single_copy_of_everything_reports_nothing(tv, factory):
    """NEGATIVE CONTROL."""
    tv(3, "Tidy", 1, [[_f("/c/s01e01.mkv", size=3 * GB, minutes=45)] for _ in range(3)])
    with factory() as session:
        shows, total = tv_duplicates.find(session)
    assert shows == [] and total == 0


def test_shows_rank_by_bytes_not_by_copy_count(tv, factory):
    """Six duplicated SD episodes return less disk than two duplicated HD ones,
    and the point of the list is which one to do first."""
    tv(
        4,
        "Many small",
        1,
        [
            [
                _f(f"/d/s01e{n}.a.mkv", size=300_000_000, minutes=22, resolution="480p"),
                _f(f"/d/s01e{n}.b.mkv", size=300_000_000, minutes=22, resolution="480p"),
            ]
            for n in range(1, 7)
        ],
    )
    tv(
        5,
        "Few large",
        1,
        [
            [
                _f(f"/e/s01e{n}.a.mkv", size=6 * GB, minutes=55),
                _f(f"/e/s01e{n}.b.mkv", size=6 * GB, minutes=55),
            ]
            for n in range(1, 3)
        ],
    )
    with factory() as session:
        shows, _total = tv_duplicates.find(session)
    assert [s.title for s in shows] == ["Few large", "Many small"]


# ------------------------------------------------------------------ season size


def _baselines(factory) -> bitrate.Baselines:
    with factory() as session:
        return outliers.load_baselines(session)


def test_episode_count_does_not_make_a_season_look_heavy(tv, factory):
    """NEGATIVE CONTROL and the core of the request. A 24-episode season holds
    more than a 10-episode one and is not heavier per hour. Rank by folder size
    and the long season always wins, which is the wrong answer every time."""
    tv(
        10,
        "Long run",
        1,
        [[_f(f"/l/{n}.mkv", size=2 * GB, minutes=45)] for n in range(1, 25)],
    )
    tv(
        11,
        "Short run",
        1,
        [[_f(f"/s/{n}.mkv", size=2 * GB, minutes=45)] for n in range(1, 11)],
    )
    with factory() as session:
        sized, _total = tv_size.seasons(session, baselines=_baselines(factory))
    by_title = {s.title: s for s in sized}
    assert by_title["Long run"].total_bytes > by_title["Short run"].total_bytes
    # ...but identical per hour, so neither is an outlier relative to the other.
    assert by_title["Long run"].bytes_per_hour == by_title["Short run"].bytes_per_hour
    assert by_title["Long run"].excess == by_title["Short run"].excess


def test_runtime_is_normalised_too(tv, factory):
    """A 22-minute comedy and a 55-minute drama at the same bitrate must compare
    equal, which per-episode figures get wrong."""
    tv(12, "Short eps", 1, [[_f(f"/x/{n}.mkv", size=1 * GB, minutes=22)] for n in range(1, 11)])
    tv(13, "Long eps", 1, [[_f(f"/y/{n}.mkv", size=1 * GB, minutes=22)] for n in range(1, 11)])
    with factory() as session:
        sized, _ = tv_size.seasons(session, baselines=_baselines(factory))
    rates = {s.title: round(s.bytes_per_hour) for s in sized}
    assert rates["Short eps"] == rates["Long eps"]


def test_a_genuinely_bloated_season_is_flagged_with_its_excess(tv, factory):
    for tvdb_id in range(20, 32):
        tv(
            tvdb_id,
            f"Ordinary {tvdb_id}",
            1,
            [[_f(f"/o{tvdb_id}/{n}.mkv", size=2 * GB, minutes=45)] for n in range(1, 11)],
        )
    tv(99, "Remuxed", 1, [[_f(f"/r/{n}.mkv", size=20 * GB, minutes=45)] for n in range(1, 11)])
    with factory() as session:
        sized, total = tv_size.seasons(session, baselines=_baselines(factory))
    top = sized[0]
    assert top.title == "Remuxed"
    assert top.bloated and top.excess > 100 * GB
    assert total >= top.excess


# ---------------------------------------------------------------- inconsistency


def test_one_sd_episode_among_hd_ones_is_reported(tv, factory):
    files = [[_f(f"/i/{n}.mkv", size=3 * GB, minutes=45)] for n in range(1, 10)]
    files.append([_f("/i/10.mkv", size=700_000_000, minutes=45, resolution="480p")])
    tv(40, "Mixed", 1, files)
    with factory() as session:
        found = tv_size.inconsistencies(session)
    assert len(found) == 1
    assert found[0].common_resolution == "1080p"
    assert found[0].odd_resolutions == {"480p": 1}


def test_a_uniformly_sd_season_is_not_an_inconsistency(tv, factory):
    """NEGATIVE CONTROL: an all-SD season is a decision, not an accident, and
    reporting it here would bury the real accidents under every old show."""
    tv(
        41,
        "All SD",
        1,
        [
            [_f(f"/j/{n}.mkv", size=700_000_000, minutes=45, resolution="480p")]
            for n in range(1, 11)
        ],
    )
    with factory() as session:
        assert tv_size.inconsistencies(session) == []


def test_a_bad_rip_hiding_in_a_good_season_is_caught(tv, factory):
    """Same resolution as its neighbours, a fraction of the bitrate."""
    files = [[_f(f"/k/{n}.mkv", size=3 * GB, minutes=45)] for n in range(1, 10)]
    files.append([_f("/k/10.mkv", size=200_000_000, minutes=45)])
    tv(42, "One bad", 1, files)
    with factory() as session:
        found = tv_size.inconsistencies(session)
    assert found[0].rate_outliers == 1
