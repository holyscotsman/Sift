"""Recognition — would a guest browsing the shelf recognise this title?

This is the axis the library is actually curated on, and it is **not quality**. A
video store stocked what people would pick up: every big release, good or awful,
plus the classics wall. It never carried an unknown regional indie. So a famously
bad film belongs on the shelf and a forgotten one does not, however it was
reviewed.

The previous scoring measured quality and used vote counts only to decide how much
to trust the rating — which made fame a *liability* (more voters agreeing a film is
bad pushed it further toward removal) and obscurity a *shield* (few voters pulled a
mediocre film up toward the neutral prior). Exactly backwards for this purpose.

Two properties are load-bearing here:

**Era normalisation.** TMDB's audience skews modern; a 1975 film will never match a
2015 film on raw vote count at equal fame. Comparing globally quietly condemns the
entire classics wall, so recognition is measured against same-decade peers.

**Canon protection.** An acclaimed obscure film and a forgotten straight-to-video
drama look identical on vote count alone. The curated lists (Criterion, cult, IMDb
top) are what separate them, so list membership floors the score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Vote counts that read as "widely seen", per release decade. TMDB's userbase grew
# with the internet, so the same cultural footprint yields wildly different vote
# totals across eras — these are the rough per-decade equivalents of "famous".
_DECADE_REFERENCE_VOTES = {
    1920: 300,
    1930: 500,
    1940: 500,
    1950: 700,
    1960: 900,
    1970: 1200,
    1980: 1800,
    1990: 2500,
    2000: 4000,
    2010: 6000,
    2020: 5000,  # dips again: recent films haven't finished accumulating votes
}
_FALLBACK_REFERENCE_VOTES = 3000

# A theatrical run, a major studio, or a studio-scale budget all mean the title was
# *pushed at* an audience — the thing that makes a bad film recognisable anyway.
_THEATRICAL_BOOST = 0.22
_BUDGET_BOOST = 0.15
_STUDIO_BUDGET_FLOOR = 20_000_000

# Being on a human-reviewed canon list is a direct statement that the title matters,
# which is the only thing that saves a genuinely obscure but important film.
_CANON_FLOOR = 0.75

# Franchise membership makes a weak entry recognisable by association (Batman &
# Robin, Highlander II) — but only when that entry itself reached cinemas. Without
# the theatrical gate this would stock fourth-tier direct-to-video spin-offs that
# inherit a famous name they never earned.
_FRANCHISE_BOOST = 0.12


def _decade_reference(year: int | None) -> int:
    if year is None:
        return _FALLBACK_REFERENCE_VOTES
    decade = (year // 10) * 10
    if decade < 1920:
        decade = 1920
    return _DECADE_REFERENCE_VOTES.get(decade, _FALLBACK_REFERENCE_VOTES)


# Curve shape. Reach is votes-as-a-fraction-of-the-era-reference, run through a
# saturating hyperbola x/(x+k). A log ratio was tried first and is wrong here: it
# compresses the low end so hard that 60 ratings still scored ~0.5, i.e. "plenty of
# people have seen this", which is the opposite of true. This shape stays near zero
# for genuinely unseen films and saturates as the era reference is approached.
_REACH_HALF_SATURATION = 0.25


def vote_reach(votes: int | None, year: int | None) -> float:
    """0–1 reach from vote volume, judged against same-decade peers."""
    if not votes or votes <= 0:
        return 0.0
    ratio = votes / _decade_reference(year)
    return max(0.0, min(1.0, ratio / (ratio + _REACH_HALF_SATURATION)))


@dataclass(frozen=True)
class Recognition:
    """How recognisable a title is, plus the evidence behind the number."""

    score: float  # 0–1
    reasons: list[str]

    @property
    def tier(self) -> str:
        if self.score >= 0.70:
            return "household"
        if self.score >= 0.40:
            return "known"
        return "obscure"


def recognise(
    *,
    votes: int | None,
    year: int | None,
    us_theatrical: bool = False,
    budget: int | None = None,
    on_canon_list: bool = False,
    in_franchise: bool = False,
    cast_fame: float = 0.0,
) -> Recognition:
    """Score a title's public footprint. Deterministic; no AI involved.

    ``cast_fame`` is a 0–1 caller-supplied hint (how well known the top-billed
    cast is). It's additive and small — a recognisable face lifts a forgettable
    film, but never rescues one nobody released.
    """
    reasons: list[str] = []
    base = vote_reach(votes, year)
    if votes:
        reasons.append(f"{votes:,} ratings for a {year or 'unknown'} release")

    score = base
    if us_theatrical:
        score += _THEATRICAL_BOOST
        reasons.append("had a theatrical run")
    if budget and budget >= _STUDIO_BUDGET_FLOOR:
        score += _BUDGET_BOOST
        reasons.append(f"studio-scale budget (${budget / 1_000_000:.0f}M)")
    if in_franchise and us_theatrical:
        # Gated on theatrical deliberately — see _FRANCHISE_BOOST.
        score += _FRANCHISE_BOOST
        reasons.append("part of a franchise people know")
    if cast_fame > 0:
        score += 0.10 * max(0.0, min(1.0, cast_fame))
        reasons.append("recognisable cast")

    score = max(0.0, min(1.0, score))

    if on_canon_list:
        # A floor, not a boost: canonised films are kept even when nothing else
        # about them reads as widely seen. This is what stops a Criterion sweep
        # deleting the very titles the Missing page tells you to acquire.
        if score < _CANON_FLOOR:
            reasons.append("on a curated canon list")
        score = max(score, _CANON_FLOOR)

    if not reasons:
        reasons.append("no signal that anyone has seen this")
    return Recognition(round(score, 3), reasons)


def from_movie_facts(facts: dict[str, Any]) -> Recognition:
    """Convenience wrapper for a stored-movie dict (keeps callers out of kwargs)."""
    return recognise(
        votes=facts.get("votes"),
        year=facts.get("year"),
        us_theatrical=bool(facts.get("us_theatrical")),
        budget=facts.get("budget"),
        on_canon_list=bool(facts.get("on_canon_list")),
        in_franchise=bool(facts.get("in_franchise")),
        cast_fame=float(facts.get("cast_fame") or 0.0),
    )
