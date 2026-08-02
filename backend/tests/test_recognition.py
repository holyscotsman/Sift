"""Recognition scoring — the axis the library is curated on.

The whole point is that this must NOT track quality. Each test here is one of the
owner's own examples, and the negative controls are the cases that make the naive
version wrong.
"""

from __future__ import annotations

from sift.analysis.recognition import recognise, vote_reach


def _r(**kw):
    kw.setdefault("votes", None)
    kw.setdefault("year", None)
    return recognise(**kw)


# ------------------------------------------------------------------- era fairness


def test_reach_is_judged_against_the_same_decade_not_globally():
    """A 1975 film will never match a 2015 film on raw votes at equal fame. Judging
    globally would quietly condemn the entire classics wall."""
    old = vote_reach(1200, 1975)
    new = vote_reach(1200, 2015)
    assert old > new  # same votes reads as far more famous for an older film
    # And equivalent-for-their-era counts land in the same place.
    assert abs(vote_reach(1200, 1975) - vote_reach(6000, 2015)) < 0.05


def test_reach_stays_near_zero_for_genuinely_unseen_films():
    """Negative control on the curve shape. A log ratio scored 60 votes at ~0.5,
    i.e. 'widely seen', which is the opposite of true."""
    assert vote_reach(60, 2003) < 0.10
    assert vote_reach(140, 1976) < 0.40
    assert vote_reach(0, 1990) == 0.0
    assert vote_reach(None, 1990) == 0.0


# --------------------------------------------------------- the owner's own cases


def test_famous_but_terrible_films_are_recognisable():
    """Battlefield Earth / Snow White / Animal Farm: awful, and kept on purpose —
    people watch them *because* of the notoriety. Rating is not consulted at all."""
    for votes, year, budget in [(5200, 2000, 44_000_000), (2600, 2025, 30_000_000)]:
        got = _r(votes=votes, year=year, us_theatrical=True, budget=budget)
        assert got.tier == "household", got


def test_unknown_independent_films_are_obscure():
    """The 1976 indie and the 1995 straight-to-video nobody has heard of."""
    assert _r(votes=140, year=1976).tier == "obscure"
    assert _r(votes=90, year=1995).tier == "obscure"
    assert _r(votes=60, year=2003).tier == "obscure"


def test_a_canon_list_rescues_an_obscure_but_important_film():
    """The trap: an acclaimed obscure film and a forgotten one look identical on
    votes alone. Without this floor, culling the obscure would delete exactly the
    Criterion titles the Missing page tells you to acquire."""
    # 80 ratings on a 1968 release is genuinely unseen even by that era's standard
    # (420 would read as "known", and fairly so).
    bare = _r(votes=80, year=1968)
    listed = _r(votes=80, year=1968, on_canon_list=True)
    assert bare.tier == "obscure"
    assert listed.tier == "household"
    assert "curated canon list" in " ".join(listed.reasons)


def test_franchise_fame_is_not_inherited_by_direct_to_video_spinoffs():
    """A weak entry in a famous franchise is recognisable only if it actually
    reached cinemas. Ungated, this stocks fourth-tier DTV cash-ins that inherit a
    name they never earned."""
    theatrical = _r(votes=1500, year=1991, us_theatrical=True, in_franchise=True)
    direct_to_video = _r(votes=210, year=2007, in_franchise=True)
    assert theatrical.tier == "household"
    assert direct_to_video.tier == "obscure"  # the boost did not apply


def test_a_theatrical_run_lifts_an_otherwise_thin_title():
    """Being pushed at an audience is what makes a bad film recognisable anyway."""
    assert _r(votes=800, year=1985, us_theatrical=True).score > _r(votes=800, year=1985).score


def test_nothing_at_all_scores_zero_and_says_why():
    got = _r()
    assert got.score == 0.0 and got.tier == "obscure"
    assert "no signal" in got.reasons[0]


def test_score_never_leaves_the_unit_interval():
    """Boosts stack; a blockbuster must clamp rather than run past 1.0."""
    piled_on = _r(
        votes=90_000,
        year=2015,
        us_theatrical=True,
        budget=250_000_000,
        in_franchise=True,
        cast_fame=1.0,
        on_canon_list=True,
    )
    assert piled_on.score == 1.0
