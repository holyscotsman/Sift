"""Smarter junk classification — context rules that override rating alone.

The deterministic rating/engagement score (``scoring.py``) answers "is this
statistically low?". This layer answers "given *what kind of film* it is, do we keep
or cut it?" — the owner's rules:

* Resembles porn                         → **remove** (always).
* Recognized cult classic                → **keep** (even if it scored low).
* Had a US theatrical release            → **keep**.
* Low-scoring independent                → **remove**.
* Low-scoring international, not cult     → **remove**.
* otherwise                              → defer to the deterministic score.

Pure and side-effect free: it takes plain facts + a "scored low" flag and returns a
verdict + human reason. The authored answer key still decides *correctness* in-game;
this only decides *library curation*, and never uses an LLM.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Verdict(enum.StrEnum):
    PROTECT = "protect"  # keep regardless of the numeric score
    REMOVE = "remove"  # cut regardless of the numeric score
    NEUTRAL = "neutral"  # defer to the deterministic junk score


@dataclass(frozen=True)
class MovieFacts:
    us_theatrical: bool = False
    is_adult: bool = False
    is_independent: bool = False
    is_international: bool = False
    is_cult: bool = False


@dataclass(frozen=True)
class Classification:
    verdict: Verdict
    reason: str


def classify(facts: MovieFacts, *, scored_low: bool) -> Classification:
    """Apply the owner's rules as a priority cascade. ``scored_low`` is the numeric
    verdict (rating/engagement put it at or above the borderline cut)."""
    # 1. Porn-like content is always cut.
    if facts.is_adult:
        return Classification(Verdict.REMOVE, "Resembles adult / pornographic content.")
    # 2. A cult classic is always kept — this is the explicit exception to "scored low".
    if facts.is_cult:
        return Classification(Verdict.PROTECT, "Recognized cult classic — kept despite the score.")
    # 3. A theatrical-scale release (US theatrical run, major studio, or a
    #    studio-scale budget) is kept — even a famously bad one; people watch
    #    those *because* they're bad.
    if facts.us_theatrical:
        return Classification(
            Verdict.PROTECT, "Theatrical-scale release (theatrical run / major studio)."
        )
    # 4. Low-scoring independents and (non-cult) international films are cut.
    if scored_low and facts.is_independent:
        return Classification(Verdict.REMOVE, "Low-rated independent film.")
    if scored_low and facts.is_international:
        return Classification(
            Verdict.REMOVE, "Low-rated international film that isn't a cult classic."
        )
    # 5. Nothing decisive — let the deterministic score stand.
    return Classification(Verdict.NEUTRAL, "")
