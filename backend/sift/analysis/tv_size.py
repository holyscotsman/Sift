"""Seasons that weigh more than they should, and seasons that disagree with themselves.

Two questions, both of which "gigabytes per season" answers wrongly.

**Which season is heavy?** A ten-episode run and a twenty-four-episode run are not
comparable by folder size, and neither are twenty-two-minute and sixty-minute
episodes. Normalising to bytes per hour removes both distortions at once, and
holding resolution and codec constant removes the third.

**Does a season agree with itself?** A single 1080p episode in an otherwise SD
season, or one file at five times its neighbours' bitrate, is a different problem
from a uniformly heavy season — it is usually an accident of how the season was
assembled, and fixing it costs almost nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import median
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Episode, MediaFile, Season, Show
from . import bitrate

# How far one episode may sit from its season's own rate before it reads as an
# accident rather than ordinary variation. Generous, because a season legitimately
# varies — a finale runs long, a clip show compresses well.
_EPISODE_OUTLIER_RATIO = 2.5

_RESOLUTION_RANK = {"480p": 0, "720p": 1, "1080p": 2, "1440p": 3, "2160p": 4}


@dataclass(frozen=True)
class SeasonSize:
    tvdb_id: int
    title: str
    season_number: int
    air_year: int | None
    episode_count: int
    total_bytes: int
    total_hours: float
    bytes_per_hour: float
    resolution: str | None
    video_codec: str | None
    # Bytes above what a season of this resolution and codec would ordinarily
    # weigh for the same number of hours.
    excess: int
    bloated: bool

    @property
    def per_episode(self) -> int:
        return self.total_bytes // self.episode_count if self.episode_count else 0


@dataclass(frozen=True)
class Inconsistency:
    """A season whose episodes do not match one another."""

    tvdb_id: int
    title: str
    season_number: int
    # The resolution most of the season is in.
    common_resolution: str | None
    odd_resolutions: dict[str, int]
    # Episodes at a wildly different bitrate despite matching resolution.
    rate_outliers: int
    reasons: list[str]

    @property
    def episodes_affected(self) -> int:
        return sum(self.odd_resolutions.values()) + self.rate_outliers


def dominant(
    values: Sequence[str | None], *, rank: Callable[[str], float] | None = None
) -> str | None:
    """The most common value, with ties broken deterministically.

    ``max(set(values), key=values.count)`` looks equivalent and is not: on a tie it
    returns whichever tied value ``set`` iteration happens to reach first, and that
    order depends on Python's per-process hash seed. A season split evenly between
    1080p and 480p therefore read as either one, **changing between runs of the
    same code over the same library** — and this value decides whether an
    irreversible quality downgrade gets proposed and how large its saving looks.

    Ties are broken toward the *lowest* ``rank``, which for both callers is the
    conservative direction: the lower resolution, and the less efficient codec.
    Both make a proposed downgrade look smaller rather than larger, which is the
    right way to be wrong about a destructive suggestion. With no rank, the order
    is alphabetical — arbitrary, but stable.
    """
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    most = max(counts.values())
    # Insertion-ordered, so this list is itself deterministic.
    tied = [value for value, n in counts.items() if n == most]
    if len(tied) == 1:
        return tied[0]
    return min(tied, key=rank) if rank is not None else min(tied)


def resolution_rank(value: str) -> float:
    """Ladder position, for tie-breaking toward the lower rung."""
    return _RESOLUTION_RANK.get(value, -1)


def _dominant(values: Sequence[str | None]) -> str | None:
    return dominant(values, rank=resolution_rank)


class SeasonFile(NamedTuple):
    """The only four fields any season-level question asks of a file."""

    size: int | None
    duration_ms: int | None
    resolution: str | None
    video_codec: str | None


class SeasonGroup(NamedTuple):
    tvdb_id: int
    season_number: int
    air_year: int | None
    files: list[SeasonFile]


def load_seasons(session: Session) -> dict[tuple[int, int], SeasonGroup]:
    """Every season's files, as columns rather than entities.

    Selecting ``MediaFile`` itself made SQLAlchemy build a fully instrumented,
    identity-mapped object per row — tens of thousands of them on a real library —
    to read four attributes off each and throw the rest away.

    Three callers ask the same question, so the query lives here rather than being
    written out three times — but each call still executes it. Hoisting the result
    up to a single per-request load is a further win and a larger change.

    Shows are deliberately *not* returned: there are a few hundred at most, and the
    callers that need their facts fetch them whole in one query.
    """
    rows = session.execute(
        select(
            MediaFile.size,
            MediaFile.duration_ms,
            MediaFile.resolution,
            MediaFile.video_codec,
            Season.season_number,
            Season.air_year,
            Show.tvdb_id,
        )
        .join(Episode, Episode.id == MediaFile.episode_id)
        .join(Season, Season.id == Episode.season_id)
        .join(Show, Show.tvdb_id == Season.show_id)
    )
    grouped: dict[tuple[int, int], SeasonGroup] = {}
    for size, duration_ms, resolution, codec, number, air_year, tvdb_id in rows:
        key = (tvdb_id, number)
        group = grouped.get(key)
        if group is None:
            group = SeasonGroup(tvdb_id, number, air_year, [])
            grouped[key] = group
        group.files.append(SeasonFile(size, duration_ms, resolution, codec))
    return grouped


def load_shows(session: Session) -> dict[int, Show]:
    """Every show by tvdb id. Few enough rows that one whole read is cheaper than
    joining them onto every file."""
    return {show.tvdb_id: show for show in session.scalars(select(Show))}


def seasons(
    session: Session,
    *,
    baselines: bitrate.Baselines,
    limit: int = 200,
    groups: dict[tuple[int, int], SeasonGroup] | None = None,
    shows: dict[int, Show] | None = None,
) -> tuple[list[SeasonSize], int]:
    """Seasons ranked by how much more disk they use than their peers.

    ``groups`` and ``shows`` let a caller that has already loaded them — the
    reclaim ledger asks two separate questions of the same rows — skip a second
    read. Omitted, they are loaded here.
    """
    out: list[SeasonSize] = []
    if shows is None:
        shows = load_shows(session)
    if groups is None:
        groups = load_seasons(session)
    for (tvdb_id, number), group in groups.items():
        files = group.files
        total_bytes = sum(f.size or 0 for f in files)
        total_ms = sum(f.duration_ms or 0 for f in files)
        if not total_bytes or not total_ms:
            continue
        show = shows[tvdb_id]
        resolution = _dominant([f.resolution for f in files])
        codec = _dominant([f.video_codec for f in files])
        verdict = bitrate.judge(
            size=total_bytes,
            duration_ms=total_ms,
            resolution=resolution,
            codec=codec,
            baselines=baselines,
        )
        if verdict is None:
            continue
        out.append(
            SeasonSize(
                tvdb_id=tvdb_id,
                title=show.title,
                season_number=number,
                air_year=group.air_year,
                episode_count=len(files),
                total_bytes=total_bytes,
                total_hours=total_ms / 3_600_000,
                bytes_per_hour=verdict.rate,
                resolution=resolution,
                video_codec=codec,
                excess=verdict.excess,
                bloated=verdict.bloated,
            )
        )
    out.sort(key=lambda s: (-s.excess, s.tvdb_id, s.season_number))
    total = sum(s.excess for s in out if s.bloated)
    return out[: max(1, limit)], total


def inconsistencies(
    session: Session,
    *,
    limit: int = 200,
    groups: dict[tuple[int, int], SeasonGroup] | None = None,
    shows: dict[int, Show] | None = None,
) -> list[Inconsistency]:
    """Seasons whose episodes disagree with one another.

    Judged against the season itself rather than the library. A season entirely in
    SD is a decision; one SD episode among twenty in 1080p is an accident, and it
    is the accident that is worth reporting.

    ``groups`` and ``shows`` take the same injected reads as :func:`seasons`, for
    the same reason: the storage page asks both questions of one set of rows, and
    the join behind them is the widest in the app.
    """
    out: list[Inconsistency] = []
    if shows is None:
        shows = load_shows(session)
    if groups is None:
        groups = load_seasons(session)
    for (tvdb_id, number), group in groups.items():
        files = group.files
        if len(files) < 3:
            # Too few to have a "most of the season" to differ from.
            continue
        show = shows[tvdb_id]
        resolutions = [f.resolution for f in files if f.resolution]
        common = _dominant(resolutions)
        odd: dict[str, int] = {}
        for value in resolutions:
            if value != common:
                odd[value] = odd.get(value, 0) + 1

        rates = [
            r
            for r in (bitrate.bytes_per_hour(f.size, f.duration_ms) for f in files)
            if r is not None
        ]
        rate_outliers = 0
        if len(rates) >= 3:
            mid = median(rates)
            if mid > 0:
                rate_outliers = sum(
                    1
                    for r in rates
                    if r > mid * _EPISODE_OUTLIER_RATIO or r < mid / _EPISODE_OUTLIER_RATIO
                )

        if not odd and not rate_outliers:
            continue

        reasons: list[str] = []
        if odd and common:
            worse = sorted(
                odd, key=lambda r: _RESOLUTION_RANK.get(r, -1) - _RESOLUTION_RANK.get(common, -1)
            )
            reasons.append(
                f"mostly {common}, but {sum(odd.values())} episode(s) at "
                f"{', '.join(worse)}"
            )
        if rate_outliers:
            reasons.append(
                f"{rate_outliers} episode(s) far off the season's own bitrate — "
                "usually a bad rip or a stray high-quality file"
            )
        out.append(
            Inconsistency(
                tvdb_id=tvdb_id,
                title=show.title,
                season_number=number,
                common_resolution=common,
                odd_resolutions=odd,
                rate_outliers=rate_outliers,
                reasons=reasons,
            )
        )
    out.sort(key=lambda i: (-i.episodes_affected, i.tvdb_id, i.season_number))
    return out[: max(1, limit)]
