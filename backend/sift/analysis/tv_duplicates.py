"""Episodes held more than once, ranked by the disk it would return.

The TV counterpart to ``duplicates``, and it carries the same reassurance: every
episode survives, only the surplus copies go, so there is no curation judgement
to get wrong.

What makes it harder than the film case is that several files under one episode
does not always mean a duplicate. Three situations look alike from a file count
and need telling apart:

**A multi-episode file** — one "S01E01-E02" covering two episodes. Handled at
ingest, where a file is identified by its path, so it is stored once no matter
how many episodes point at it.

**Split parts** — a long episode delivered as two files. Deleting one of those
destroys the episode, and duration alone cannot tell them apart: two halves of a
sixty-minute episode and two copies of a thirty-minute one look identical. Plex
already draws the distinction structurally — one ``Media`` is one presentation
and its ``Part`` entries are that presentation split across files — so the answer
is read out of ``part_group`` rather than inferred.

**Genuine copies** — the same episode twice, usually at different qualities.
These are what this reports.

Ranking is by reclaimable bytes rather than by copy count, so a show with two
duplicated hours of 1080p correctly outranks one with six duplicated SD ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Episode, MediaFile, Season, Show

# Order of preference when deciding which copy to keep.
_RESOLUTION_RANK = {"480p": 0, "720p": 1, "1080p": 2, "1440p": 3, "2160p": 4}

# Episodes per read, matching the chunk size the ingest writers use.
_CHUNK = 500


@dataclass(frozen=True)
class Copy:
    """One presentation of an episode — possibly spanning several files."""

    paths: list[str]
    size: int
    duration_ms: int | None
    resolution: str | None
    video_codec: str | None
    # The one worth keeping: highest resolution, then largest.
    keep: bool

    @property
    def file_count(self) -> int:
        return len(self.paths)


@dataclass(frozen=True)
class DuplicateEpisode:
    season_number: int
    episode_number: int
    title: str | None
    copies: list[Copy]

    @property
    def surplus(self) -> int:
        return max(0, len(self.copies) - 1)

    @property
    def reclaimable(self) -> int:
        return sum(c.size for c in self.copies if not c.keep)


@dataclass(frozen=True)
class ShowDuplicates:
    tvdb_id: int
    title: str
    library_section: str | None
    episodes: list[DuplicateEpisode]

    @property
    def surplus(self) -> int:
        return sum(e.surplus for e in self.episodes)

    @property
    def reclaimable(self) -> int:
        return sum(e.reclaimable for e in self.episodes)


def _presentations(files: list[MediaFile]) -> list[list[MediaFile]]:
    """Split an episode's files into the distinct presentations they make up.

    Files sharing a ``part_group`` are one thing in several pieces. A file with no
    group is treated as its own presentation, which is the safe reading: it may be
    counted as a removable copy, never as a discardable half of something else.
    """
    groups: dict[str, list[MediaFile]] = {}
    for index, media_file in enumerate(files):
        key = media_file.part_group or f"file:{media_file.id or index}"
        groups.setdefault(key, []).append(media_file)
    return list(groups.values())


def _rank(group: list[MediaFile]) -> tuple[int, int]:
    best = max((_RESOLUTION_RANK.get(f.resolution or "", -1) for f in group), default=-1)
    return best, sum(f.size or 0 for f in group)


def find(session: Session, *, limit: int = 200) -> tuple[list[ShowDuplicates], int]:
    """Shows holding duplicate episodes, biggest reclaim first.

    Returns ``(shows, total_reclaimable)`` — the second across the whole library,
    not just the returned page.
    """
    # Ask the database which episodes have more than one file before reading any
    # of them. An episode with a single file cannot be duplicated, and in a real
    # library that is nearly all of them — hydrating the whole join first meant
    # building four ORM objects per file for tens of thousands of files, then
    # discarding all but a few percent.
    duplicated = [
        episode_id
        for (episode_id,) in session.execute(
            select(MediaFile.episode_id)
            .where(MediaFile.episode_id.is_not(None))
            .group_by(MediaFile.episode_id)
            .having(func.count(MediaFile.id) > 1)
        )
    ]

    by_episode: dict[int, list[MediaFile]] = {}
    meta: dict[int, tuple[Episode, Season, Show]] = {}
    for start in range(0, len(duplicated), _CHUNK):
        batch = duplicated[start : start + _CHUNK]
        rows = session.execute(
            select(MediaFile, Episode, Season, Show)
            .join(Episode, Episode.id == MediaFile.episode_id)
            .join(Season, Season.id == Episode.season_id)
            .join(Show, Show.tvdb_id == Season.show_id)
            .where(MediaFile.episode_id.in_(batch))
        )
        for media_file, episode, season, show in rows:
            by_episode.setdefault(episode.id, []).append(media_file)
            meta[episode.id] = (episode, season, show)

    per_show: dict[int, list[DuplicateEpisode]] = {}
    titles: dict[int, tuple[str, str | None]] = {}
    for episode_id, files in by_episode.items():
        if len(files) < 2:
            continue
        groups = _presentations(files)
        if len(groups) < 2:
            # One presentation split across files. Every one of them is needed.
            continue
        keeper = max(groups, key=_rank)
        episode, season, show = meta[episode_id]
        per_show.setdefault(show.tvdb_id, []).append(
            DuplicateEpisode(
                season_number=season.season_number,
                episode_number=episode.episode_number,
                title=episode.title,
                copies=[
                    Copy(
                        paths=[f.path for f in group if f.path],
                        size=sum(f.size or 0 for f in group),
                        duration_ms=sum(f.duration_ms or 0 for f in group) or None,
                        resolution=max(
                            (f.resolution for f in group if f.resolution),
                            key=lambda r: _RESOLUTION_RANK.get(r, -1),
                            default=None,
                        ),
                        video_codec=next((f.video_codec for f in group if f.video_codec), None),
                        keep=group is keeper,
                    )
                    for group in groups
                ],
            )
        )
        titles[show.tvdb_id] = (show.title, show.library_section)

    shows = [
        ShowDuplicates(
            tvdb_id=tvdb_id,
            title=titles[tvdb_id][0],
            library_section=titles[tvdb_id][1],
            episodes=sorted(eps, key=lambda e: (e.season_number, e.episode_number)),
        )
        for tvdb_id, eps in per_show.items()
    ]
    shows.sort(key=lambda s: s.reclaimable, reverse=True)
    total = sum(s.reclaimable for s in shows)
    return shows[: max(1, limit)], total
