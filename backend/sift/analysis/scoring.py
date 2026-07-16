"""Pure, deterministic junk-scoring functions.

No side effects and no ORM types in the signatures, so this is trivially
golden-testable. The composite junk score is a weighted blend of independently
computed signals; each signal's contribution (0–1, higher = more junk-like) and a
human-readable detail are preserved for the UI and for the LLM to explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..config import JunkThresholds


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    weight: float
    contribution: float  # 0..1, higher = more junk-like
    available: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "contribution": round(self.contribution, 3),
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ScoreResult:
    junk_score: float  # 0..100
    band: str  # keep | borderline | junk
    signals: list[Signal]
    kids_guard: bool


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def bayesian_rating(value: float, votes: int | None, *, prior_mean: float, min_votes: int) -> float:
    """IMDb-style weighted rating: few votes pull the score toward the prior mean."""
    v = max(0, votes or 0)
    if v == 0:
        return prior_mean
    return (v / (v + min_votes)) * value + (min_votes / (v + min_votes)) * prior_mean


def rating_signal(value: float | None, votes: int | None, thr: JunkThresholds) -> Signal:
    if value is None:
        return Signal("rating", "External rating", 0.6, 0.0, False, "no rating")
    weighted = bayesian_rating(value, votes, prior_mean=thr.rating_prior, min_votes=thr.min_votes)
    # Above floor+1.5 → not junk; below floor−1.5 → fully junk; linear between.
    contribution = _clamp((thr.rating_floor + 1.5 - weighted) / 3.0)
    return Signal(
        "rating", "External rating", 0.6, contribution, True,
        f"weighted {weighted:.1f}/10 ({votes or 0} votes)",
    )


def engagement_signal(
    watch: list[dict[str, Any]],
    thr: JunkThresholds,
    *,
    available: bool,
    now: datetime | None = None,
) -> Signal:
    if not available:
        return Signal("engagement", "Watch history", 0.4, 0.0, False, "no watch data")
    now = now or datetime.now(UTC)
    total_plays = sum(int(w.get("plays") or 0) for w in watch)
    if total_plays == 0:
        return Signal("engagement", "Watch history", 0.4, 0.85, True, "never played")

    contribution = 0.0
    details: list[str] = []
    last_dates = [w["last_played_at"] for w in watch if w.get("last_played_at")]
    if last_dates:
        newest = max(last_dates)
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=UTC)
        years = (now - newest).days / 365.25
        if years > thr.unwatched_years:
            over = (years - thr.unwatched_years) / max(thr.unwatched_years, 1)
            contribution = max(contribution, _clamp(0.4 + over * 0.6))
            details.append(f"last played {years:.0f}y ago")
    comps = [w["completion_pct"] for w in watch if w.get("completion_pct") is not None]
    if comps:
        avg = sum(comps) / len(comps)
        if avg < thr.low_completion_pct:
            contribution = max(contribution, 0.5)
            details.append(f"{avg * 100:.0f}% avg completion")
    if not details:
        details.append(f"{total_plays} play(s)")
    return Signal("engagement", "Watch history", 0.4, contribution, True, ", ".join(details))


def band(score: float, thr: JunkThresholds) -> str:
    if score >= thr.junk_cutoff:
        return "junk"
    if score >= thr.borderline_cutoff:
        return "borderline"
    return "keep"


def compose(signals: list[Signal], thr: JunkThresholds) -> float:
    available = [s for s in signals if s.available]
    if not available:
        return 0.0
    weight_sum = sum(s.weight for s in available)
    score = 100.0 * sum(s.weight * s.contribution for s in available) / weight_sum
    return round(score, 1)


def rationale(signals: list[dict[str, Any]], band_value: str) -> str:
    """A plain-language, deterministic explanation built from the signals.

    Phase 2 will let the LLM rewrite this more naturally — but it is explicitly
    forbidden from re-judging or changing the score; this stays the ground truth.
    """
    contributing = sorted(
        (s for s in signals if s.get("available") and float(s.get("contribution", 0)) >= 0.4),
        key=lambda s: float(s.get("contribution", 0)),
        reverse=True,
    )
    if not contributing:
        return "No strong removal signals — looks worth keeping."
    lead = {
        "junk": "Strong removal candidate",
        "borderline": "Possible removal",
        "keep": "Minor flags",
    }.get(band_value, "Flags")
    return f"{lead}: " + "; ".join(str(s.get("detail", "")) for s in contributing) + "."


def score_movie(
    *,
    rating_value: float | None,
    rating_votes: int | None,
    watch: list[dict[str, Any]],
    is_kids: bool,
    thr: JunkThresholds,
    engagement_available: bool,
    now: datetime | None = None,
) -> ScoreResult:
    signals = [
        rating_signal(rating_value, rating_votes, thr),
        engagement_signal(watch, thr, available=engagement_available, now=now),
    ]
    score = compose(signals, thr)
    return ScoreResult(score, band(score, thr), signals, kids_guard=is_kids)
