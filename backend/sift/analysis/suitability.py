"""Should this show be in HD, or is SD the right answer?

Three signals, all deterministic. No AI decides any of it.

**What the master can deliver.** A show shot on NTSC video in 2001 has no HD to
be had; a 1080p file of it is an upscale that costs disk and returns nothing.
This is judged *per season*, not per show, and the difference is not academic:
Scrubs began in 2001 and ended in 2010, SpongeBob runs from 1999 into the 2020s.
A show is not one answer.

**How much the picture rewards pixels.** Anime holds fine linework and gradients
that fall apart at SD; nature documentary is photographed to be looked at. A flat
western cartoon and a twenty-two-minute sitcom are not, and storing them at high
bitrate buys nothing anyone will ever see.

**How attentively it is actually watched.** Completion, rewatching, recency, and
above all the resolution genuinely delivered to a player. A show only ever
streamed at 720p on a phone is not being asked for 4K.

Two things this deliberately does not do.

It does not consult ``recognition``. That module measures public footprint, and
SpongeBob's is enormous — feeding fame into a quality decision would push exactly
the wrong show toward HD. Fame answers whether a title belongs on the shelf, not
what resolution it deserves.

It does not force a verdict. Where the evidence is thin the answer is "not
enough to say", which is a real outcome rather than a bucket of last resort. And
the bar is deliberately asymmetric: recommending an upgrade only costs disk and
can be undone, while recommending a downgrade destroys picture that cannot be
recovered without re-acquiring the show. The second therefore needs every signal
to agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Rungs, in order. Everything below is expressed as an index into this.
LADDER = ("480p", "720p", "1080p", "2160p")
_INDEX = {name: i for i, name in enumerate(LADDER)}

# What a season's air year says the master can deliver. Broadcast television
# moved to HD over a period, not on a date, so these are the years by which the
# format was normal rather than the years it first appeared.
_CEILING_BY_YEAR = ((2016, "2160p"), (2009, "1080p"), (2004, "720p"), (0, "480p"))

# 2160p is only ever a ceiling where a 4K file already exists. Almost nothing
# broadcast is mastered at 4K, and assuming it would recommend upgrades that can
# never be satisfied.
_UHD_NEEDS_EVIDENCE = True

# Visual demand, evaluated in order — first match wins.
_ANIME_HINTS = ("anime", "japanese animation")
_NATURE_HINTS = ("nature", "wildlife", "natural history", "documentary series")

_DEMAND_ANIME = 0.90
_DEMAND_NATURE = 0.90
_DEMAND_PRESTIGE = 0.75
_DEMAND_ACTION = 0.70
_DEMAND_WESTERN_ANIMATION = 0.35
_DEMAND_SITCOM = 0.30
_DEMAND_KIDS = 0.25
_DEMAND_DEFAULT = 0.55

# A show untouched for this long is not being watched, whatever the totals say.
_STALE_DAYS = 540

# Below this, demand is low enough that a downgrade is worth considering at all.
_DOWNGRADE_DEMAND_CEILING = 0.45
# And attention must be at or below this, or absent entirely.
_DOWNGRADE_ATTENTION_CEILING = 0.35


@dataclass(frozen=True)
class ShowFacts:
    """Everything the decision reads. Plain data, so it is trivially testable."""

    title: str
    genres: list[str]
    keywords: list[str]
    original_language: str | None
    runtime: int | None
    is_kids: bool
    # Watch evidence. All optional — absent means no evidence, never "unwatched".
    plays: int = 0
    mean_completion: float | None = None
    last_played_at: datetime | None = None
    typical_stream_height: int | None = None


@dataclass(frozen=True)
class Suitability:
    """A verdict for one season, with the evidence that produced it."""

    season_number: int
    air_year: int | None
    current: str | None
    target: str | None
    ceiling: str | None
    demand: float
    attention: float | None
    # upgrade | downgrade | fine | unknown
    verdict: str
    reasons: list[str]

    @property
    def actionable(self) -> bool:
        return self.verdict in ("upgrade", "downgrade")


def source_ceiling(air_year: int | None, *, has_uhd_file: bool = False) -> str | None:
    """The best the master plausibly is, from the season's own air year."""
    if air_year is None:
        return None
    for year, rung in _CEILING_BY_YEAR:
        if air_year >= year:
            if rung == "2160p" and _UHD_NEEDS_EVIDENCE and not has_uhd_file:
                return "1080p"
            return rung
    return "480p"


def _has(values: list[str], hints: tuple[str, ...]) -> bool:
    lowered = [v.lower() for v in values]
    return any(hint in value for value in lowered for hint in hints)


def visual_demand(facts: ShowFacts) -> tuple[float, str]:
    """How much this show's picture rewards being stored well."""
    genres = [g.lower() for g in facts.genres]
    animated = "animation" in genres
    japanese = (facts.original_language or "").lower() in ("ja", "japanese")

    if animated and (japanese or _has(facts.keywords, _ANIME_HINTS)):
        return _DEMAND_ANIME, "anime — fine linework and gradients fall apart at low bitrate"
    if "documentary" in genres and _has(facts.keywords, _NATURE_HINTS):
        return _DEMAND_NATURE, "nature documentary — photographed to be looked at"
    if animated:
        return _DEMAND_WESTERN_ANIMATION, "flat animation — holds up well at low bitrate"
    if facts.is_kids:
        return _DEMAND_KIDS, "a kids library title"
    runtime = facts.runtime or 0
    if runtime and runtime <= 30 and (
        "comedy" in genres or "talk" in genres or "reality" in genres
    ):
        return _DEMAND_SITCOM, "a short-form comedy — detail is not what you watch it for"
    if runtime >= 45 and (
        {"drama", "sci-fi & fantasy", "science fiction", "thriller", "mystery"} & set(genres)
    ):
        return _DEMAND_PRESTIGE, "long-form drama — the photography is part of it"
    if {"action & adventure", "action", "war & politics"} & set(genres):
        return _DEMAND_ACTION, "action — motion and detail both matter"
    return _DEMAND_DEFAULT, "no strong signal either way"


def attention(facts: ShowFacts, *, now: datetime | None = None) -> tuple[float | None, str]:
    """How closely this show is actually watched, or ``None`` with no evidence."""
    if not facts.plays:
        return None, "no watch history"
    now = now or datetime.now(UTC)
    parts: list[str] = []

    completion = facts.mean_completion if facts.mean_completion is not None else 0.5
    score = completion
    parts.append(f"episodes watched to {completion:.0%} on average")

    last = facts.last_played_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        days = (now - last).days
        if days > _STALE_DAYS:
            score *= 0.4
            parts.append(f"nothing played for {days // 30} months")
    if facts.plays >= 20:
        score = min(1.0, score + 0.15)
        parts.append(f"{facts.plays} plays")

    if facts.typical_stream_height:
        parts.append(f"usually streamed at {facts.typical_stream_height}p")
    return max(0.0, min(1.0, score)), "; ".join(parts)


def _rung_from_height(height: int | None) -> str | None:
    """Which rung a pixel height sits on.

    Strictly greater-than at each boundary, matching the ladder ingest uses: a
    stream 720 pixels high *is* 720p, and rounding it up to 1080p would quietly
    defeat the cap it feeds.
    """
    if not height:
        return None
    if height > 1600:
        return "2160p"
    if height > 720:
        return "1080p"
    if height > 576:
        return "720p"
    return "480p"


def _target(demand: float, att: float | None) -> str:
    want = demand if att is None else 0.6 * demand + 0.4 * att
    if want >= 0.80:
        return "2160p"
    if want >= 0.55:
        return "1080p"
    if want >= 0.35:
        return "720p"
    return "480p"


def assess(
    facts: ShowFacts,
    *,
    season_number: int,
    air_year: int | None,
    current: str | None,
    has_uhd_file: bool = False,
    now: datetime | None = None,
) -> Suitability:
    """Judge one season."""
    demand, demand_reason = visual_demand(facts)
    att, attention_reason = attention(facts, now=now)
    ceiling = source_ceiling(air_year, has_uhd_file=has_uhd_file)

    wanted = _target(demand, att)
    # The delivered resolution caps the target too: storing more than is ever
    # played back is disk spent on something nobody sees.
    played = _rung_from_height(facts.typical_stream_height)
    if played is not None and _INDEX[played] < _INDEX[wanted]:
        wanted = played
    target = wanted
    if ceiling is not None and _INDEX[ceiling] < _INDEX[wanted]:
        target = ceiling

    reasons = [demand_reason, attention_reason]
    if ceiling is not None and air_year is not None:
        reasons.append(f"{air_year} season — the master is {ceiling} at best")

    if current is None or current not in _INDEX:
        return Suitability(
            season_number, air_year, current, target, ceiling, demand, att,
            "unknown", [*reasons, "nothing on disk to judge"],
        )

    here, want = _INDEX[current], _INDEX[target]

    if want > here:
        # Cheap and reversible: it only costs disk, and the old file is replaced
        # by a better one rather than destroyed.
        return Suitability(
            season_number, air_year, current, target, ceiling, demand, att,
            "upgrade", [*reasons, f"held at {current}, worth {target}"],
        )

    if want < here:
        # Irreversible, so every signal has to agree. Any one of these failing
        # leaves the season alone.
        if demand > _DOWNGRADE_DEMAND_CEILING:
            return Suitability(
                season_number, air_year, current, target, ceiling, demand, att,
                "fine", [*reasons, "larger than needed, but the picture earns it"],
            )
        if att is not None and att > _DOWNGRADE_ATTENTION_CEILING:
            return Suitability(
                season_number, air_year, current, target, ceiling, demand, att,
                "fine", [*reasons, "larger than needed, but you actually watch it"],
            )
        if ceiling is None:
            return Suitability(
                season_number, air_year, current, target, ceiling, demand, att,
                "unknown",
                [*reasons, "no air year, so no way to know what the master can deliver"],
            )
        return Suitability(
            season_number, air_year, current, target, ceiling, demand, att,
            "downgrade", [*reasons, f"held at {current}, {target} is enough for this"],
        )

    return Suitability(
        season_number, air_year, current, target, ceiling, demand, att,
        "fine", [*reasons, f"{current} is the right place for this"],
    )
