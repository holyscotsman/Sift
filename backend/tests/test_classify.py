"""Golden rules for the smarter junk classifier (owner's stated policy)."""

from __future__ import annotations

from sift.analysis.classify import Classification, MovieFacts, Verdict, classify


def _v(facts: MovieFacts, *, low: bool) -> Verdict:
    result = classify(facts, scored_low=low)
    assert isinstance(result, Classification)
    return result.verdict


def test_us_theatrical_is_kept_even_when_low():
    assert _v(MovieFacts(us_theatrical=True), low=True) == Verdict.PROTECT


def test_low_independent_is_removed():
    assert _v(MovieFacts(is_independent=True), low=True) == Verdict.REMOVE
    # NEGATIVE CONTROL: a well-scoring independent is not force-removed.
    assert _v(MovieFacts(is_independent=True), low=False) == Verdict.NEUTRAL


def test_adult_is_always_removed():
    assert _v(MovieFacts(is_adult=True), low=False) == Verdict.REMOVE
    # Adult outranks a theatrical keep.
    assert _v(MovieFacts(is_adult=True, us_theatrical=True), low=False) == Verdict.REMOVE


def test_low_international_not_cult_is_removed():
    assert _v(MovieFacts(is_international=True), low=True) == Verdict.REMOVE


def test_low_international_but_cult_is_kept():
    # The cult exception wins over the international-removal rule.
    assert _v(MovieFacts(is_international=True, is_cult=True), low=True) == Verdict.PROTECT


def test_low_but_cult_is_kept():
    assert _v(MovieFacts(is_cult=True), low=True) == Verdict.PROTECT


def test_cult_outranks_independent_removal():
    assert _v(MovieFacts(is_independent=True, is_cult=True), low=True) == Verdict.PROTECT


def test_no_signals_defers_to_score():
    assert _v(MovieFacts(), low=True) == Verdict.NEUTRAL
    assert _v(MovieFacts(), low=False) == Verdict.NEUTRAL


def test_reason_is_populated_for_decisive_verdicts():
    assert classify(MovieFacts(is_adult=True), scored_low=False).reason
    assert classify(MovieFacts(us_theatrical=True), scored_low=True).reason
    assert classify(MovieFacts(), scored_low=True).reason == ""
