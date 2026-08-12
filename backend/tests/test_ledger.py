"""The reclaim ledger and the target planner.

The claim under test is the ordering, not the arithmetic: safe space is spent
before risky space, whatever the individual sizes are.
"""

from __future__ import annotations

import pytest

from sift.analysis import ledger
from sift.db.models import Episode, MediaFile, Movie, PlexCopy, Season, Show

GB = 1_000_000_000
MIN_MS = 60_000


@pytest.fixture
def library(factory):
    def _build() -> None:
        with factory() as session:
            # A duplicated film: two copies, one removable. Tier 0.
            session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, runtime=136))
            for key, size in (("1001", 8 * GB), ("1002", 5 * GB)):
                session.add(
                    PlexCopy(rating_key=key, movie_tmdb_id=603, library_section="Movies")
                )
                session.add(
                    MediaFile(
                        movie_tmdb_id=603,
                        rating_key=key,
                        path=f"/movies/matrix.{key}.mkv",
                        size=size,
                        duration_ms=136 * MIN_MS,
                        resolution="1080p",
                        video_codec="h264",
                        source="plex",
                    )
                )

            # Ordinary films, so the baselines mean something.
            for i in range(10):
                tmdb_id = 2000 + i
                session.add(Movie(tmdb_id=tmdb_id, title=f"Ordinary {i}", year=2015, runtime=120))
                session.add(
                    MediaFile(
                        movie_tmdb_id=tmdb_id,
                        path=f"/movies/ordinary{i}.mkv",
                        size=6 * GB,
                        duration_ms=120 * MIN_MS,
                        resolution="1080p",
                        video_codec="h264",
                        source="plex",
                    )
                )

            # A sitcom from 2001 held in HD and never watched. Tier 2.
            show = Show(
                tvdb_id=76156,
                title="Scrubs",
                genres=["Comedy"],
                runtime=22,
                library_section="TV",
                in_plex=True,
            )
            session.add(show)
            season = Season(show_id=76156, season_number=1, air_year=2001)
            session.add(season)
            session.flush()
            for n in range(1, 11):
                episode = Episode(season_id=season.id, episode_number=n, has_file=True)
                session.add(episode)
                session.flush()
                session.add(
                    MediaFile(
                        episode_id=episode.id,
                        path=f"/tv/scrubs/s01e{n:02d}.mkv",
                        part_group=f"scrubs-{n}",
                        size=3 * GB,
                        duration_ms=22 * MIN_MS,
                        resolution="1080p",
                        video_codec="h264",
                        source="plex",
                    )
                )
            session.commit()

    return _build


def test_the_ledger_gathers_every_kind_into_one_list(library, factory):
    library()
    with factory() as session:
        book = ledger.build(session)
    kinds = {f.kind for f in book.findings}
    assert "duplicate_movie" in kinds
    assert "quality_downgrade" in kinds
    assert book.total_reclaimable > 0


def test_safe_findings_come_first_however_large_the_risky_ones_are(library, factory):
    """The substance of the module. A list sorted purely by size would put an
    irreversible downgrade above a duplicate that costs nothing to remove."""
    library()
    with factory() as session:
        book = ledger.build(session)
    tiers = [f.risk_tier for f in book.findings]
    assert tiers == sorted(tiers)

    tier0 = [f for f in book.findings if f.risk_tier == ledger.TIER_FREE]
    tier2 = [f for f in book.findings if f.risk_tier == ledger.TIER_JUDGEMENT]
    assert tier0 and tier2
    # The risky finding really is the larger one, so the ordering is doing work
    # rather than agreeing with size by accident.
    assert max(f.bytes_reclaimable for f in tier2) > max(
        f.bytes_reclaimable for f in tier0
    )


def test_a_small_target_is_met_without_any_judgement_calls(library, factory):
    """Most of the disk comes back before a question of taste is asked."""
    library()
    with factory() as session:
        book = ledger.build(session)
    result = ledger.plan(book, 1 * GB)
    assert result.reached
    assert result.highest_tier == ledger.TIER_FREE
    assert all(s.finding.risk_tier == ledger.TIER_FREE for s in result.steps)


def test_a_larger_target_escalates_but_only_as_far_as_it_must(library, factory):
    library()
    with factory() as session:
        book = ledger.build(session)
    free = book.by_tier.get(ledger.TIER_FREE, 0)
    result = ledger.plan(book, free + 1)
    assert result.highest_tier > ledger.TIER_FREE
    # Every zero-loss finding is spent before the first risky one is proposed.
    spent_free = sum(
        s.finding.bytes_reclaimable
        for s in result.steps
        if s.finding.risk_tier == ledger.TIER_FREE
    )
    assert spent_free == free


def test_an_impossible_target_says_so_rather_than_overpromising(library, factory):
    """NEGATIVE CONTROL: claiming a target was reached when it was not is the
    one answer that would send someone deleting things for nothing."""
    library()
    with factory() as session:
        book = ledger.build(session)
    result = ledger.plan(book, 500_000 * GB)
    assert not result.reached
    assert result.total == book.total_reclaimable


def test_a_tidy_library_yields_an_empty_ledger(factory):
    """NEGATIVE CONTROL."""
    with factory() as session:
        book = ledger.build(session)
    assert book.findings == []
    assert book.total_reclaimable == 0
    assert ledger.plan(book, 10 * GB).steps == []


def test_a_duplicate_is_costed_from_the_copy_that_would_actually_go(library, factory):
    """Two copies at 8 GB and 5 GB return 5 GB, not 8 and not 13. Getting this
    wrong makes the headline figure a fiction."""
    library()
    with factory() as session:
        book = ledger.build(session)
    dupe = next(f for f in book.findings if f.kind == "duplicate_movie")
    assert dupe.bytes_reclaimable == 5 * GB
