"""The v2 junk score — computed in shadow, shown to nobody yet.

The v1 score in ``scoring.py`` blends signals additively: every signal pushes on
the same number, so enough small pushes add up to a removal verdict. That is the
wrong shape for this problem. Obscurity is the only thing that should *press*
toward deletion; watching a film, or having asked for it, should be able to stop
that pressure outright rather than merely offset a fraction of it.

So v2 states the asymmetry as arithmetic instead of as weights::

    pressure   = w_rec · (1 − recognition)
    protection = noisy_or(engagement, intent)
    score      = 100 · clamp(pressure · (1 − protection) + w_q · quality_deficit)

Full protection zeroes any amount of obscurity pressure; zero protection leaves
it untouched. There is no combination of weak signals that adds up to condemning
a film somebody actually watched.

Three rules this module exists to keep, each of which v1 broke at some point:

* **Never played is not evidence.** Most of a well-stocked shelf is unwatched —
  that is what a shelf is *for*. Engagement's floor is "contributes nothing",
  never "condemns". Same for a film abandoned eight minutes in: weak protection,
  not negative protection.
* **Rating cannot outvote recognition.** 3,200 people agreeing a film is bad once
  pushed it toward deletion; that was 2607.13.0's bug. Here quality is capped
  structurally at less than a third of the smaller of the two real signals, and
  ``test_quality_cannot_outvote`` pins the ratio rather than trusting memory.
* **Thin evidence abstains.** A title TMDB has not reached, a film owned for a
  week, a scan where Tautulli was down — all return ``insufficient`` rather than
  guessing. Abstention is a first-class answer, not a rounding of "keep".

Pure and side-effect free: no ORM types in any signature, so the whole thing is
golden-testable. Nothing here reaches the UI — ``compute_and_store`` writes it to
its own table and the Junk screen keeps showing v1 until the owner has read the
shadow diff and said otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..config import JunkThresholds
from .classify import Verdict
from .recognition import Recognition
from .scoring import bayesian_rating

# --- Weights -----------------------------------------------------------------
#
# Phase 1 ships hand-set weights chosen to reproduce v1's rank order, not to
# change the answers. Calibration against owner labels is a later phase and lands
# as an audited config change, never as a runtime fit.

W_RECOGNITION = 1.0
W_ENGAGEMENT = 0.6
W_INTENT = 0.4
W_QUALITY = 0.15

# Engagement's two independent protective routes, combined noisy-OR: either one
# alone is enough, which is the point of the form.
W_RECENCY = 0.8
W_DEPTH = 0.9

# A play protects for about this long before it stops counting for much. Watching
# something five years ago is not the same claim as watching it last month.
ENGAGEMENT_HALF_LIFE_YEARS = 2.5

# Asking for a film decays more slowly than watching one — but it does decay. A
# title requested four years ago and never played is drifting toward ordinary
# unwatched, which is exactly what the queue is for.
INTENT_HALF_LIFE_YEARS = 4.0

# Radarr keeps monitoring this title, which somebody chose at some point. Mild,
# and deliberately far below an explicit request.
MONITORED_PROTECTION = 0.25
REQUESTED_PROTECTION = 0.9

# --- Bands -------------------------------------------------------------------
#
# Higher than v1's 60/40. v1's cutoffs were set when rating led the score and
# everything clustered mid-range; under the multiplicative form an unprotected
# obscure title lands far higher, and 60 would sweep in titles the owner would
# not recognise as junk. This is the change that visibly shrinks the queue, and
# it is exactly why v2 stays in shadow until the diff has been read.

JUNK_CUTOFF = 70.0
BORDERLINE_CUTOFF = 50.0

# A band changes only when the score clears the boundary by this much, so a title
# rescoring by half a point does not flap between queues every scan.
HYSTERESIS = 3.0

# Below this share of the signal weight actually being backed by data, the title
# abstains instead of scoring.
MIN_EVIDENCE = 0.5

# A film owned for less than this has thin absence-of-engagement rather than
# damning absence-of-engagement — nobody has had the chance to watch it yet.
OWNERSHIP_EVIDENCE_DAYS = 90

BANDS = ("keep", "borderline", "junk")
INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class SignalV2:
    """One signal group's answer, plus how much data was behind it."""

    key: str
    label: str
    weight: float
    value: float  # 0..1 — pressure for recognition/quality, protection otherwise
    evidence: float  # 0..1 — how much real data backed `value`
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "value": round(self.value, 3),
            "evidence": round(self.evidence, 3),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FactsV2:
    """Everything the cascade needs, as plain facts rather than ORM rows."""

    keep_override: bool = False
    is_kids: bool = False
    is_adult: bool = False
    is_cult: bool = False
    on_canon_list: bool = False
    us_theatrical: bool = False
    is_independent: bool = False
    is_international: bool = False


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    verdict: Verdict
    reason: str


@dataclass(frozen=True)
class ScoreV2Result:
    score: float  # 0..100
    band: str  # keep | borderline | junk | insufficient
    confidence: float  # 0..1 evidence mass
    rule: str  # which P-rule fired
    verdict: Verdict
    reason: str
    signals: list[SignalV2]

    def as_dict(self) -> dict[str, object]:
        return {
            "signals": [s.as_dict() for s in self.signals],
            "band": self.band,
            "confidence": round(self.confidence, 3),
            "rule": self.rule,
            "verdict": str(self.verdict),
            "verdict_reason": self.reason,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _decay(years: float, half_life: float) -> float:
    """Exponential decay, halving every ``half_life`` years."""
    if years <= 0:
        return 1.0
    return math.exp(-math.log(2) * years / half_life)


def noisy_or(*values: float) -> float:
    """Combine independent protective signals: either alone is enough.

    Used rather than a sum because two half-strength protections should land
    short of certainty, not add to it — and because no number of weak signals
    should ever exceed one strong one.
    """
    remaining = 1.0
    for v in values:
        remaining *= 1.0 - _clamp(v)
    return 1.0 - remaining


def _years_since(when: datetime | None, now: datetime) -> float | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (now - when).days / 365.25)


def recognition_signal(rec: Recognition | None) -> SignalV2:
    """Obscurity pressure — the only signal that pushes toward deletion.

    Absent enrichment this carries zero evidence rather than zero recognition:
    a title TMDB has not reached yet must not read as "nobody has heard of it",
    which would propose deleting the library after a partial scan.
    """
    if rec is None:
        return SignalV2(
            "recognition", "Public recognition", W_RECOGNITION, 0.0, 0.0, "not enriched yet"
        )
    return SignalV2(
        "recognition",
        "Public recognition",
        W_RECOGNITION,
        _clamp(1.0 - rec.score),
        1.0,
        f"{rec.tier} — {rec.reasons[0]}",
    )


def engagement_signal(
    watch: list[dict[str, Any]],
    thr: JunkThresholds,
    *,
    available: bool,
    owned_days: float | None,
    now: datetime,
) -> SignalV2:
    """Protection earned by being watched. Its floor is zero, never negative."""
    if not available:
        return SignalV2("engagement", "Watch history", W_ENGAGEMENT, 0.0, 0.0, "no watch data")

    # Owned briefly → "never played" is thin evidence, not damning evidence.
    evidence = 1.0
    if owned_days is not None and owned_days < OWNERSHIP_EVIDENCE_DAYS:
        evidence = _clamp(0.3 + 0.7 * owned_days / OWNERSHIP_EVIDENCE_DAYS)

    total_plays = sum(int(w.get("plays") or 0) for w in watch)
    if total_plays == 0:
        return SignalV2(
            "engagement", "Watch history", W_ENGAGEMENT, 0.0, evidence, "never played"
        )

    dates = [w["last_played_at"] for w in watch if w.get("last_played_at")]
    recency = 0.0
    detail_bits: list[str] = [f"{total_plays} play(s)"]
    if dates:
        newest = max(d for d in dates if isinstance(d, datetime))
        years = _years_since(newest, now) or 0.0
        recency = _decay(years, ENGAGEMENT_HALF_LIFE_YEARS)
        detail_bits.append(f"last played {years:.1f}y ago")

    comps = [w["completion_pct"] for w in watch if w.get("completion_pct") is not None]
    if comps:
        avg = sum(float(c) for c in comps) / len(comps)
        # Finished is strong; sampled-and-abandoned is weak but still protective.
        # Abandonment is absence of evidence of value, not evidence of absence.
        quality = 0.25 if avg < thr.low_completion_pct else _clamp(0.4 + avg * 0.6)
        detail_bits.append(f"{avg * 100:.0f}% avg completion")
    else:
        quality = 0.6  # played, completion unknown

    depth = _clamp(min(1.0, total_plays / 2.0) * quality)
    protect = noisy_or(recency * W_RECENCY, depth * W_DEPTH)
    return SignalV2(
        "engagement", "Watch history", W_ENGAGEMENT, protect, evidence, ", ".join(detail_bits)
    )


def intent_signal(
    *,
    requested_at: datetime | None,
    monitored: bool,
    added_at: datetime | None,
    now: datetime,
) -> SignalV2:
    """Protection earned by somebody here having asked for the film.

    The audit trail already records who asked for what; this is the first signal
    that reads it. A request is a strong claim on a title even when nobody has
    got round to watching it.
    """
    parts: list[float] = []
    detail_bits: list[str] = []
    if requested_at is not None:
        years = _years_since(requested_at, now) or 0.0
        parts.append(REQUESTED_PROTECTION * _decay(years, INTENT_HALF_LIFE_YEARS))
        detail_bits.append(f"requested {years:.1f}y ago")
    if monitored:
        parts.append(MONITORED_PROTECTION)
        detail_bits.append("monitored in Radarr")

    # Evidence is about whether *absent* intent is known. If we know when the
    # title arrived, "nobody asked for this" is a fact; if we don't, it is a gap.
    evidence = 1.0 if (added_at is not None or requested_at is not None or monitored) else 0.0
    return SignalV2(
        "intent",
        "Requested or monitored",
        W_INTENT,
        noisy_or(*parts) if parts else 0.0,
        evidence,
        ", ".join(detail_bits) or "nobody asked for this",
    )


def quality_signal(value: float | None, votes: int | None, thr: JunkThresholds) -> SignalV2:
    """The tiebreaker, and nothing more.

    It may separate two equally unrecognised, equally unwatched titles. It may
    never condemn a famous one — see ``W_QUALITY`` and the invariant test.
    """
    if value is None:
        return SignalV2("quality", "External rating", W_QUALITY, 0.0, 0.0, "no rating")
    weighted = bayesian_rating(value, votes, prior_mean=thr.rating_prior, min_votes=thr.min_votes)
    deficit = _clamp((thr.rating_floor + 1.5 - weighted) / 3.0)
    return SignalV2(
        "quality",
        "External rating",
        W_QUALITY,
        deficit,
        1.0,
        f"weighted {weighted:.1f}/10 ({votes or 0} votes)",
    )


# --- The protection cascade, as a table --------------------------------------
#
# v1 expressed these as an if-ladder inside classify(). Stating them as ordered,
# named rules means the drawer can say which one fired, and a test can enumerate
# them rather than trusting that the ladder was read correctly.

_CASCADE: tuple[tuple[str, str, Verdict, str], ...] = (
    ("P0", "keep_override", Verdict.PROTECT, "Owner marked this Keep."),
    ("P1", "is_kids", Verdict.PROTECT, "Kids-section title — never auto-flagged."),
    ("P2", "is_cult", Verdict.PROTECT, "Recognized cult classic."),
    ("P2", "on_canon_list", Verdict.PROTECT, "On the validated canon (tier 1-3)."),
    ("P3", "us_theatrical", Verdict.PROTECT, "Theatrical-scale release."),
    ("P4", "is_adult", Verdict.REMOVE, "Resembles adult / pornographic content."),
)


def apply_rules(facts: FactsV2, *, scored_low: bool) -> RuleOutcome:
    """First matching rule wins. P4 is deliberately below the protections: an
    adult title that is also on a curated list is a data error, and protecting it
    is the safe way to be wrong."""
    for name, attr, verdict, reason in _CASCADE:
        if getattr(facts, attr):
            return RuleOutcome(name, verdict, reason)
    if scored_low and facts.is_independent and not facts.is_cult:
        return RuleOutcome("P5", Verdict.REMOVE, "Low-scoring independent film.")
    if scored_low and facts.is_international and not facts.is_cult:
        return RuleOutcome("P6", Verdict.REMOVE, "Low-scoring international film, not cult.")
    return RuleOutcome("P7", Verdict.NEUTRAL, "")


def raw_band(score: float) -> str:
    if score >= JUNK_CUTOFF:
        return "junk"
    if score >= BORDERLINE_CUTOFF:
        return "borderline"
    return "keep"


def band_with_hysteresis(score: float, previous: str | None, *, rule_changed: bool = False) -> str:
    """Move bands only on a decisive change.

    Without this a title sitting a fraction under a cutoff joins and leaves the
    junk queue on alternate scans as votes tick over — which reads as the app
    changing its mind, and teaches the owner to distrust it. A changed P-rule is
    a changed *fact*, so it moves immediately regardless of margin.
    """
    now_band = raw_band(score)
    if previous is None or previous not in BANDS or previous == now_band or rule_changed:
        return now_band
    shifted = score - HYSTERESIS if BANDS.index(now_band) > BANDS.index(previous) else (
        score + HYSTERESIS
    )
    return now_band if raw_band(shifted) == now_band else previous


def evidence_mass(signals: list[SignalV2]) -> float:
    total = sum(s.weight for s in signals)
    if total <= 0:
        return 0.0
    return sum(s.weight * s.evidence for s in signals) / total


def score_movie_v2(
    *,
    rating_value: float | None,
    rating_votes: int | None,
    watch: list[dict[str, Any]],
    facts: FactsV2,
    thr: JunkThresholds,
    engagement_available: bool,
    recognition: Recognition | None = None,
    requested_at: datetime | None = None,
    monitored: bool = False,
    added_at: datetime | None = None,
    previous_band: str | None = None,
    previous_rule: str | None = None,
    now: datetime | None = None,
) -> ScoreV2Result:
    """Compose the v2 removal score. Deterministic; no model involved."""
    now = now or datetime.now(UTC)
    owned_days = None
    if added_at is not None:
        years = _years_since(added_at, now)
        owned_days = None if years is None else years * 365.25

    rec = recognition_signal(recognition)
    eng = engagement_signal(
        watch, thr, available=engagement_available, owned_days=owned_days, now=now
    )
    intent = intent_signal(
        requested_at=requested_at, monitored=monitored, added_at=added_at, now=now
    )
    qual = quality_signal(rating_value, rating_votes, thr)
    signals = [rec, eng, intent, qual]

    pressure = rec.weight * rec.value
    protection = noisy_or(eng.value, intent.value)
    score = 100.0 * _clamp(pressure * (1.0 - protection) + qual.weight * qual.value)
    score = round(score, 1)

    confidence = evidence_mass(signals)
    outcome = apply_rules(facts, scored_low=raw_band(score) != "keep")

    if confidence < MIN_EVIDENCE:
        # Abstain. Not "keep" — the distinction is the whole point: keep is a
        # judgement, insufficient is the honest absence of one.
        return ScoreV2Result(
            score, INSUFFICIENT, confidence, outcome.rule, outcome.verdict, outcome.reason, signals
        )

    rule_changed = previous_rule is not None and previous_rule != outcome.rule
    band_value = band_with_hysteresis(score, previous_band, rule_changed=rule_changed)
    return ScoreV2Result(
        score, band_value, confidence, outcome.rule, outcome.verdict, outcome.reason, signals
    )
