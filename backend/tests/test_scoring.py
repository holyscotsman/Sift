"""Golden tests for deterministic junk scoring (with negative controls)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sift.analysis import scoring
from sift.config import JunkThresholds

THR = JunkThresholds()
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RECENT = datetime(2025, 6, 1, tzinfo=UTC)


def test_bayesian_rating_pulls_low_vote_scores_to_prior():
    # Few votes → close to the prior (6.0); many votes → close to the raw value.
    br = scoring.bayesian_rating
    assert br(9.0, 5, prior_mean=6.0, min_votes=50) == pytest.approx(6.27, 0.05)
    assert br(9.0, 5000, prior_mean=6.0, min_votes=50) == pytest.approx(8.97, 0.05)
    assert br(9.0, 0, prior_mean=6.0, min_votes=50) == 6.0


def test_clear_junk_scores_high():
    # Low rating with many votes + never played → strong junk.
    r = scoring.score_movie(
        rating_value=3.0, rating_votes=200, watch=[], is_kids=False,
        thr=THR, engagement_available=True, now=NOW,
    )
    assert r.junk_score == pytest.approx(92.0, abs=0.5)
    assert r.band == "junk"


def test_good_movie_is_kept():
    # NEGATIVE CONTROL: a well-rated, recently-watched film must not be flagged.
    r = scoring.score_movie(
        rating_value=8.5, rating_votes=5000,
        watch=[{"plays": 3, "last_played_at": RECENT, "completion_pct": 0.95}],
        is_kids=False, thr=THR, engagement_available=True, now=NOW,
    )
    assert r.junk_score == pytest.approx(0.0, abs=0.5)
    assert r.band == "keep"


def test_kids_item_carries_guard():
    r = scoring.score_movie(
        rating_value=3.0, rating_votes=200, watch=[], is_kids=True,
        thr=THR, engagement_available=True, now=NOW,
    )
    assert r.kids_guard is True  # score still computed, but guarded downstream


def test_engagement_unavailable_falls_back_to_rating_only():
    # With no watch data (Tautulli not scanned), only the rating signal counts.
    r = scoring.score_movie(
        rating_value=3.0, rating_votes=200, watch=[], is_kids=False,
        thr=THR, engagement_available=False, now=NOW,
    )
    # rating contribution 0.9667 → 96.7, engagement excluded.
    assert r.junk_score == pytest.approx(96.7, abs=0.5)
    assert [s.available for s in r.signals] == [True, False]


def test_rationale_mentions_contributing_signals():
    r = scoring.score_movie(
        rating_value=3.0, rating_votes=200, watch=[], is_kids=False,
        thr=THR, engagement_available=True, now=NOW,
    )
    text = scoring.rationale([s.as_dict() for s in r.signals], r.band)
    assert "removal candidate" in text.lower()
    assert "never played" in text
