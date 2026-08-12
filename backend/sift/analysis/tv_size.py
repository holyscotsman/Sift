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

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

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


def _dominant(values: Sequence[str | None]) -> str | None:
    present = [v for v in values if v]
    if not present:
        return None
    return max(set(present), key=present.count)


def _load(session: Session) -> dict[tuple[int, int], list[tuple[MediaFile, Season, Show]]]:
    rows = session.execute(
        select(MediaFile, Season, Show)
        .join(Episode, Episode.id == MediaFile.episode_id)
        .join(Season, Season.id == Episode.season_id)
        .join(Show, Show.tvdb_id == Season.show_id)
    )
    grouped: dict[tuple[int, int], list[tuple[MediaFile, Season, Show]]] = {}
    for media_file, season, show in rows:
        grouped.setdefault((show.tvdb_id, season.season_number), []).append(
            (media_file, season, show)
        )
    return grouped


def seasons(
    session: Session, *, baselines: bitrate.Baselines, limit: int = 200
) -> tuple[list[SeasonSize], int]:
    """Seasons ranked by how much more disk they use than their peers."""
    out: list[SeasonSize] = []
    for (tvdb_id, number), entries in _load(session).items():
        files = [f for f, _s, _sh in entries]
        total_bytes = sum(f.size or 0 for f in files)
        total_ms = sum(f.duration_ms or 0 for f in files)
        if not total_bytes or not total_ms:
            continue
        season = entries[0][1]
        show = entries[0][2]
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
                air_year=season.air_year,
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
    out.sort(key=lambda s: s.excess, reverse=True)
    total = sum(s.excess for s in out if s.bloated)
    return out[: max(1, limit)], total


def inconsistencies(session: Session, *, limit: int = 200) -> list[Inconsistency]:
    """Seasons whose episodes disagree with one another.

    Judged against the season itself rather than the library. A season entirely in
    SD is a decision; one SD episode among twenty in 1080p is an accident, and it
    is the accident that is worth reporting.
    """
    out: list[Inconsistency] = []
    for (tvdb_id, number), entries in _load(session).items():
        files = [f for f, _s, _sh in entries]
        if len(files) < 3:
            # Too few to have a "most of the season" to differ from.
            continue
        show = entries[0][2]
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
    out.sort(key=lambda i: i.episodes_affected, reverse=True)
    return out[: max(1, limit)]
