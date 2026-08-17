"""The v2 shadow score: the invariants it exists to hold, and their controls.

Every pin here is one of the mistakes v1 actually made, expressed as a test so it
cannot be made again quietly. Each has a negative control that fails if the
implementation is broken in the obvious way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sift.analysis import scoring_v2
from sift.analysis.classify import Verdict
from sift.analysis.recognition import recognise
from sift.config import JunkThresholds

THR = JunkThresholds()
NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _obscure() -> object:
    """A genuinely unrecognised film: few votes, no theatrical run, no budget."""
    return recognise(votes=40, year=1976, us_theatrical=False, budget=None, on_canon_list=False)


def _famous() -> object:
    return recognise(
        votes=400_000, year=2005, us_theatrical=True, budget=90_000_000, on_canon_list=False
    )


def _score(**kw: object) -> scoring_v2.ScoreV2Result:
    params: dict[str, object] = {
        "rating_value": 6.5,
        "rating_votes": 5_000,
        "watch": [],
        "facts": scoring_v2.FactsV2(),
        "thr": THR,
        "engagement_available": True,
        "recognition": _obscure(),
        "added_at": NOW - timedelta(days=900),
        "now": NOW,
    }
    params.update(kw)
    return scoring_v2.score_movie_v2(**params)  # type: ignore[arg-type]


def test_quality_cannot_outvote_recognition() -> None:
    """The 2607.13.0 fix as a structural invariant rather than a memory.

    3,200 people agreeing a film is bad once pushed it toward deletion. Pin the
    weight ratio directly, so a later tweak that re-inflates quality fails here
    instead of quietly resurrecting the bug.
    """
    assert scoring_v2.W_QUALITY < min(scoring_v2.W_RECOGNITION, scoring_v2.W_ENGAGEMENT) / 3


def test_famous_but_terrible_is_not_junk() -> None:
    """NEGATIVE CONTROL for the weight ratio: a famously bad film — every rating
    signal screaming, full public recognition — must stay out of the junk band.
    Raise W_QUALITY above the ratio above and this goes red."""
    result = _score(recognition=_famous(), rating_value=2.1, rating_votes=120_000)
    assert result.band == "keep"
    assert result.score < scoring_v2.BORDERLINE_CUTOFF


def test_never_played_does_not_condemn() -> None:
    """Engagement's floor is 'contributes nothing', never 'condemns'."""
    unwatched = _score(watch=[])
    played = _score(
        watch=[{"plays": 2, "last_played_at": NOW - timedelta(days=30), "completion_pct": 0.95}]
    )
    # Watching it must lower the score; not watching it must not raise it above
    # the score of the same film with no watch data at all.
    assert played.score < unwatched.score
    assert unwatched.score == _score(engagement_available=False, added_at=None).score


def test_watching_a_film_protects_it_outright() -> None:
    """The multiplicative form: full protection zeroes obscurity pressure.

    This is the asymmetry the additive v1 could not express — there, a strong
    engagement signal could only offset a fraction of the pressure.
    """
    watched = _score(
        watch=[{"plays": 3, "last_played_at": NOW - timedelta(days=10), "completion_pct": 0.98}]
    )
    assert watched.band == "keep"


def test_abandoned_is_weak_protection_not_evidence_of_junk() -> None:
    """NEGATIVE CONTROL for the engagement floor: a film sampled and abandoned at
    8% protects *less* than one watched through, but still never scores higher
    than the same film nobody touched. Make abandonment subtract and this fails."""
    abandoned = _score(
        watch=[{"plays": 1, "last_played_at": NOW - timedelta(days=20), "completion_pct": 0.08}]
    )
    finished = _score(
        watch=[{"plays": 1, "last_played_at": NOW - timedelta(days=20), "completion_pct": 0.98}]
    )
    untouched = _score(watch=[])
    assert finished.score < abandoned.score <= untouched.score

    # And pin the floor directly rather than only through the composed score:
    # engagement's value is a protection, so it is never negative for any
    # completion figure, however dismal.
    # The weak corner is the one that matters: an old play *and* a dismal
    # completion, where every protective term is near zero and a sign error
    # would tip the whole signal into condemning the film.
    for days in (20, 365 * 3, 365 * 8, 365 * 20):
        for pct in (0.0, 0.02, 0.08, 0.24, 0.5, 1.0):
            signal = scoring_v2.engagement_signal(
                [
                    {
                        "plays": 1,
                        "last_played_at": NOW - timedelta(days=days),
                        "completion_pct": pct,
                    }
                ],
                THR,
                available=True,
                owned_days=900.0,
                now=NOW,
            )
            assert signal.value >= 0.0, (days, pct)
            # And it must never be worse for the film than having no plays at all.
            assert signal.value >= scoring_v2.engagement_signal(
                [], THR, available=True, owned_days=900.0, now=NOW
            ).value, (days, pct)


def test_a_request_protects_a_film_nobody_watched() -> None:
    """Intent: asking for a film is a claim on it even with zero plays."""
    requested = _score(requested_at=NOW - timedelta(days=120))
    ignored = _score()
    assert requested.score < ignored.score


def test_intent_decays() -> None:
    """NEGATIVE CONTROL for intent: a request from six years ago protects far less
    than one from last month. Remove the decay and these two match."""
    recent = _score(requested_at=NOW - timedelta(days=30))
    ancient = _score(requested_at=NOW - timedelta(days=365 * 6))
    assert recent.score < ancient.score


def test_unenriched_title_abstains() -> None:
    """A title TMDB hasn't reached is 'not enough to say', not 'keep'."""
    result = _score(recognition=None, rating_value=None, engagement_available=False, added_at=None)
    assert result.band == scoring_v2.INSUFFICIENT
    assert result.confidence < scoring_v2.MIN_EVIDENCE


def test_a_fully_evidenced_title_does_not_abstain() -> None:
    """NEGATIVE CONTROL for abstention: with recognition, ratings, watch data and
    an arrival date all present, the title must commit to a band. Raise
    MIN_EVIDENCE above 1.0 and this goes red."""
    result = _score()
    assert result.band in scoring_v2.BANDS
    assert result.confidence >= scoring_v2.MIN_EVIDENCE


def test_band_needs_a_margin_to_change() -> None:
    """Hysteresis: a title must clear the cutoff decisively, not by a whisker."""
    just_over = scoring_v2.JUNK_CUTOFF + 0.5
    clearly_over = scoring_v2.JUNK_CUTOFF + 3.1
    assert scoring_v2.band_with_hysteresis(just_over, "borderline") == "borderline"
    assert scoring_v2.band_with_hysteresis(clearly_over, "borderline") == "junk"


def test_hysteresis_works_downward_too() -> None:
    """NEGATIVE CONTROL: the margin must apply in both directions. An
    implementation that only guards promotion lets a title drop out of the junk
    queue on a half-point wobble, which is the same flapping in reverse."""
    assert scoring_v2.band_with_hysteresis(scoring_v2.JUNK_CUTOFF - 0.5, "junk") == "junk"
    assert scoring_v2.band_with_hysteresis(scoring_v2.JUNK_CUTOFF - 3.1, "junk") == "borderline"


def test_a_changed_rule_moves_the_band_immediately() -> None:
    """A changed fact is not a drifting number: hysteresis must not delay it."""
    assert (
        scoring_v2.band_with_hysteresis(
            scoring_v2.JUNK_CUTOFF + 0.5, "borderline", rule_changed=True
        )
        == "junk"
    )


def test_the_cascade_protects_before_it_removes() -> None:
    """Owner override, kids, cult, canon and theatrical all outrank the score."""
    facts = scoring_v2.FactsV2(keep_override=True, is_independent=True)
    assert scoring_v2.apply_rules(facts, scored_low=True).verdict == Verdict.PROTECT
    canon = scoring_v2.FactsV2(on_canon_list=True, is_independent=True)
    assert scoring_v2.apply_rules(canon, scored_low=True).rule == "P2"
    kids = scoring_v2.FactsV2(is_kids=True)
    assert scoring_v2.apply_rules(kids, scored_low=True).rule == "P1"


def test_an_unprotected_low_scorer_is_still_removable() -> None:
    """NEGATIVE CONTROL for the cascade: protection must not swallow everything.
    An obscure independent with none of the protective facts still reaches P5."""
    facts = scoring_v2.FactsV2(is_independent=True)
    outcome = scoring_v2.apply_rules(facts, scored_low=True)
    assert outcome.rule == "P5"
    assert outcome.verdict == Verdict.REMOVE


def test_adult_is_removed_but_never_over_a_protection() -> None:
    """P4 removes; but an adult flag on a canon title is a data error, and
    protecting it is the safe way to be wrong."""
    assert scoring_v2.apply_rules(scoring_v2.FactsV2(is_adult=True), scored_low=False).verdict == (
        Verdict.REMOVE
    )
    both = scoring_v2.FactsV2(is_adult=True, on_canon_list=True)
    assert scoring_v2.apply_rules(both, scored_low=False).verdict == Verdict.PROTECT


def test_noisy_or_never_exceeds_certainty() -> None:
    """Two half-strength protections land short of certainty, not past it."""
    assert scoring_v2.noisy_or(0.5, 0.5) == 0.75
    assert scoring_v2.noisy_or(0.9, 0.9, 0.9) < 1.0
    assert scoring_v2.noisy_or() == 0.0


def test_a_briefly_owned_film_has_thin_evidence() -> None:
    """NEGATIVE CONTROL for evidence weighting: 'never played' means less for a
    film that arrived last week than for one owned three years. Drop the
    ownership term and the two confidences match."""
    fresh = _score(added_at=NOW - timedelta(days=5))
    settled = _score(added_at=NOW - timedelta(days=900))
    assert fresh.confidence < settled.confidence
