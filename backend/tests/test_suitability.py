"""HD-versus-SD suitability.

The examples in these tests are the ones the feature was asked for by name:
anime and Severance should be held well; SpongeBob and Scrubs need not be. They
are here because they are the cases a naive rule gets wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sift.analysis import recognition, suitability

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _facts(**kwargs) -> suitability.ShowFacts:
    base = {
        "title": "A Show",
        "genres": [],
        "keywords": [],
        "original_language": "en",
        "runtime": 45,
        "is_kids": False,
    }
    base.update(kwargs)
    return suitability.ShowFacts(**base)


ANIME = _facts(
    title="Frieren", genres=["Animation"], original_language="ja", runtime=24
)
SPONGEBOB = _facts(
    title="SpongeBob", genres=["Animation", "Comedy"], runtime=11, is_kids=True
)
SEVERANCE = _facts(title="Severance", genres=["Drama", "Mystery"], runtime=50)
SCRUBS = _facts(title="Scrubs", genres=["Comedy"], runtime=22)


# ------------------------------------------------------------------- the ceiling


def test_the_ceiling_follows_the_season_not_the_show():
    """The reason seasons are modelled at all. Scrubs ran 2001-2010: its first
    season has no HD to be had and its last does. One answer per show is wrong
    for every long-running series."""
    assert suitability.source_ceiling(2001) == "480p"
    assert suitability.source_ceiling(2010) == "1080p"


def test_4k_is_not_assumed_without_a_file_to_prove_it():
    """NEGATIVE CONTROL: almost nothing broadcast is mastered at 4K, so assuming
    it would recommend upgrades that can never be satisfied."""
    assert suitability.source_ceiling(2022) == "1080p"
    assert suitability.source_ceiling(2022, has_uhd_file=True) == "2160p"


# ------------------------------------------------------------------ visual demand


def test_anime_and_spongebob_are_not_the_same_kind_of_animation():
    """Both are cartoons; only one falls apart at low bitrate."""
    anime_demand, _ = suitability.visual_demand(ANIME)
    sponge_demand, _ = suitability.visual_demand(SPONGEBOB)
    assert anime_demand > 0.8
    assert sponge_demand < 0.4


def test_severance_and_scrubs_are_not_the_same_kind_of_live_action():
    severance, _ = suitability.visual_demand(SEVERANCE)
    scrubs, _ = suitability.visual_demand(SCRUBS)
    assert severance > 0.7
    assert scrubs < 0.4


def test_fame_is_not_used_and_would_get_this_backwards():
    """NEGATIVE CONTROL for the trap. SpongeBob is one of the most recognised
    shows ever made and still does not need HD. Any wiring of recognition into
    this decision inverts it."""
    famous = recognition.recognise(votes=50_000, year=1999, us_theatrical=True)
    assert famous.tier == "household"

    verdict = suitability.assess(
        SPONGEBOB, season_number=1, air_year=1999, current="1080p", now=NOW
    )
    assert verdict.verdict == "downgrade"


# ---------------------------------------------------------------------- verdicts


def test_an_sd_anime_season_is_worth_upgrading():
    verdict = suitability.assess(
        ANIME, season_number=1, air_year=2023, current="480p", now=NOW
    )
    assert verdict.verdict == "upgrade"
    assert verdict.target == "1080p"


def test_an_hd_sitcom_from_2001_comes_down():
    verdict = suitability.assess(
        SCRUBS, season_number=1, air_year=2001, current="1080p", now=NOW
    )
    assert verdict.verdict == "downgrade"
    assert verdict.target == "480p"


def test_the_same_show_gets_a_different_ceiling_in_a_different_year():
    """Same show, same taste, different master — which is the whole reason the
    ceiling is per season.

    Taste says SD is enough for a sitcom either way, so both seasons come down.
    What changes is what was *available*: season 1 could never have been better
    than SD, while season 9 genuinely could have been 1080p. Judged per show,
    one of those two facts would have to be wrong.
    """
    early = suitability.assess(SCRUBS, season_number=1, air_year=2001, current="720p", now=NOW)
    late = suitability.assess(SCRUBS, season_number=9, air_year=2010, current="720p", now=NOW)
    assert early.ceiling == "480p"
    assert late.ceiling == "1080p"


def test_prestige_drama_is_left_alone_at_1080p():
    verdict = suitability.assess(
        SEVERANCE, season_number=1, air_year=2022, current="1080p", now=NOW
    )
    assert verdict.verdict == "fine"


# ------------------------------------------------- the asymmetric evidentiary bar


def test_a_show_you_actually_watch_is_not_downgraded():
    """NEGATIVE CONTROL: low demand alone is not enough. A downgrade destroys
    picture that cannot be recovered without re-acquiring the show, so every
    signal has to agree."""
    watched = _facts(
        title="Scrubs",
        genres=["Comedy"],
        runtime=22,
        plays=40,
        mean_completion=0.95,
        last_played_at=NOW - timedelta(days=3),
    )
    verdict = suitability.assess(
        watched, season_number=1, air_year=2001, current="1080p", now=NOW
    )
    assert verdict.verdict == "fine"


def test_without_an_air_year_there_is_no_verdict():
    """NEGATIVE CONTROL: with no way to know what the master can deliver, a
    downgrade is a guess — and an unrecoverable one."""
    verdict = suitability.assess(
        SCRUBS, season_number=1, air_year=None, current="1080p", now=NOW
    )
    assert verdict.verdict == "unknown"
    assert not verdict.actionable


def test_an_upgrade_needs_less_evidence_than_a_downgrade():
    """Deliberate asymmetry. An upgrade costs disk and can be undone; nothing
    about watch history is required to justify one."""
    upgrade = suitability.assess(
        ANIME, season_number=1, air_year=2023, current="480p", now=NOW
    )
    assert upgrade.verdict == "upgrade"
    assert upgrade.attention is None  # no watch data at all, and it still stands


def test_a_season_with_nothing_on_disk_gets_no_verdict():
    """NEGATIVE CONTROL."""
    verdict = suitability.assess(
        ANIME, season_number=1, air_year=2023, current=None, now=NOW
    )
    assert verdict.verdict == "unknown"


def test_a_show_only_ever_streamed_at_720p_is_not_kept_in_4k():
    """Storing more than is ever played back is disk spent on something nobody
    sees. The delivered resolution caps the target."""
    phone_only = _facts(
        title="Background",
        genres=["Documentary"],
        keywords=["nature"],
        runtime=50,
        plays=30,
        mean_completion=0.9,
        last_played_at=NOW - timedelta(days=10),
        typical_stream_height=720,
    )
    verdict = suitability.assess(
        phone_only, season_number=1, air_year=2020, current="1080p", has_uhd_file=True, now=NOW
    )
    assert verdict.target == "720p"


def test_a_stale_show_loses_attention_weight():
    """Totals alone say a show is loved forever. Recency is what stops a series
    watched once in 2019 from arguing for its own bitrate."""
    stale = _facts(
        title="Old favourite",
        genres=["Comedy"],
        runtime=22,
        plays=40,
        mean_completion=0.95,
        last_played_at=NOW - timedelta(days=1200),
    )
    fresh_score, _ = suitability.attention(
        _facts(
            title="x",
            genres=[],
            plays=40,
            mean_completion=0.95,
            last_played_at=NOW - timedelta(days=3),
        ),
        now=NOW,
    )
    stale_score, _ = suitability.attention(stale, now=NOW)
    assert stale_score is not None and fresh_score is not None
    assert stale_score < fresh_score
