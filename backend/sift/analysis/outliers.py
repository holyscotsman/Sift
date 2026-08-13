"""Films whose file size does not match the film.

Two failures at opposite ends, and neither is visible from a byte count alone.

**Too large** is answered entirely by ``bitrate`` — a file is only bloated
relative to others of its resolution and codec.

**Too small** is the more interesting one, because "under a gigabyte" describes
three completely different situations: a genuinely short film, which is fine and
must never be touched; a truncated download or a stray sample that was imported as
the feature, which is free disk; and a real feature at a bitrate that makes it
unwatchable, which wants re-acquiring rather than deleting. Deleting the first by
mistake is the worst thing this module could do, so the discriminator has to be
something better than size.

That discriminator is **the file's own duration against the runtime TMDB
published**, both of which Sift already stores. A file that runs as long as the
film is supposed to is the film; one that stops after eight minutes of a
two-hour feature is not, whatever its size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import MediaFile, Movie
from . import bitrate

# Below this a file is worth a second look. Not a verdict on its own — it is the
# trigger for asking which of the three situations this is.
SMALL_FILE_BYTES = 1_000_000_000

# A film at or under this is plausibly a short, where a small file is simply
# correct. Feature length proper starts around 40 minutes.
SHORT_FILM_MINUTES = 45

# How far a file may fall short of the published runtime before it is treated as
# truncated rather than merely trimmed. Generous, because runtimes disagree across
# cuts, regions and whether the credits were counted.
TRUNCATED_FRACTION = 0.60

# A file this far below its peers is not a compact encode, it is a bad one.
BAD_RIP_FRACTION = 0.40

_MS_PER_MINUTE = 60_000


@dataclass(frozen=True)
class SizeFinding:
    """One file that does not weigh what its film should."""

    tmdb_id: int
    title: str
    year: int | None
    # oversized | truncated | bad_rip
    kind: str
    path: str | None
    size: int
    duration_ms: int | None
    runtime_minutes: int | None
    resolution: str | None
    video_codec: str | None
    # Disk this finding would return. Deleting a truncated file returns all of it;
    # shrinking a bloated one returns only the excess.
    bytes_reclaimable: int
    reasons: list[str]

    @property
    def risk_tier(self) -> int:
        """0 when nothing of value is lost, 1 when the fix is a re-encode."""
        return 0 if self.kind == "truncated" else 1


@dataclass(frozen=True)
class OutlierReport:
    findings: list[SizeFinding]
    # Totals span the whole library, not just the returned page.
    total_reclaimable: int
    oversized_count: int
    truncated_count: int
    bad_rip_count: int
    # Small files that were inspected and cleared — almost all of them genuine
    # short films. Reported so the number is visibly *considered* rather than
    # silently dropped.
    short_films_cleared: int


def _minutes(duration_ms: int | None) -> float | None:
    return duration_ms / _MS_PER_MINUTE if duration_ms else None


def _fmt_gb(value: int) -> str:
    return f"{value / 1_000_000_000:.1f} GB"


def load_baselines(session: Session) -> bitrate.Baselines:
    """Measure the library's own norms from every file it holds."""
    rows = session.execute(
        select(
            MediaFile.resolution, MediaFile.video_codec, MediaFile.size, MediaFile.duration_ms
        )
    )
    return bitrate.build(
        bitrate.Sample(resolution=r, codec=c, size=s, duration_ms=d) for r, c, s, d in rows
    )


class FilmFile(NamedTuple):
    """One film's file, as the eight fields this module actually reads.

    Selected as columns rather than as ``MediaFile`` and ``Movie`` entities: the
    ORM builds a fully instrumented, identity-mapped object per row, and a library
    is tens of thousands of rows from which six attributes are read.
    """

    tmdb_id: int
    title: str
    year: int | None
    runtime: int | None
    path: str | None
    size: int | None
    duration_ms: int | None
    resolution: str | None
    video_codec: str | None


def _load_film_files(session: Session) -> list[FilmFile]:
    rows = session.execute(
        select(
            Movie.tmdb_id,
            Movie.title,
            Movie.year,
            Movie.runtime,
            MediaFile.path,
            MediaFile.size,
            MediaFile.duration_ms,
            MediaFile.resolution,
            MediaFile.video_codec,
        ).join(Movie, Movie.tmdb_id == MediaFile.movie_tmdb_id)
    )
    return [FilmFile(*row) for row in rows]


def _small_file_finding(
    *,
    file: FilmFile,
    baselines: bitrate.Baselines,
) -> SizeFinding | None:
    """Classify a small file, or return ``None`` when it is simply a small film."""
    runtime = file.runtime
    played = _minutes(file.duration_ms)
    size = file.size or 0

    if runtime is None or played is None:
        # No way to tell a short film from a broken one. Saying nothing is the
        # only safe answer; a delete proposed on a guess is unrecoverable.
        return None

    if played < runtime * TRUNCATED_FRACTION:
        return SizeFinding(
            tmdb_id=file.tmdb_id,
            title=file.title,
            year=file.year,
            kind="truncated",
            path=file.path,
            size=size,
            duration_ms=file.duration_ms,
            runtime_minutes=runtime,
            resolution=file.resolution,
            video_codec=file.video_codec,
            # The whole file: it is not the film, so none of it is worth keeping.
            bytes_reclaimable=size,
            reasons=[
                f"runs {played:.0f} min against a published runtime of {runtime} min",
                "a sample, a trailer, or a download that never finished",
            ],
        )

    if runtime <= SHORT_FILM_MINUTES:
        # A short film in a small file is exactly right.
        return None

    verdict = bitrate.judge(
        size=size,
        duration_ms=file.duration_ms,
        resolution=file.resolution,
        codec=file.video_codec,
        baselines=baselines,
    )
    if verdict is not None and verdict.rate < verdict.bucket.median_rate * BAD_RIP_FRACTION:
        return SizeFinding(
            tmdb_id=file.tmdb_id,
            title=file.title,
            year=file.year,
            kind="bad_rip",
            path=file.path,
            size=size,
            duration_ms=file.duration_ms,
            runtime_minutes=runtime,
            resolution=file.resolution,
            video_codec=file.video_codec,
            # Nothing to reclaim — this one wants replacing, not removing, and
            # claiming its bytes would pad the total with disk you keep using.
            bytes_reclaimable=0,
            reasons=[
                f"full length, but {verdict.ratio:.0%} of the usual rate "
                f"for {file.resolution or 'its resolution'}",
                "complete but badly encoded — worth replacing, not deleting",
            ],
        )
    return None


def find(
    session: Session, *, limit: int = 200, baselines: bitrate.Baselines | None = None
) -> OutlierReport:
    """Films that are too large or too small, biggest reclaim first.

    ``baselines`` is accepted so a caller that already measured them does not pay
    for a second full pass over every file. Left out, they are measured here, which
    is what a standalone caller wants.
    """
    if baselines is None:
        baselines = load_baselines(session)
    findings: list[SizeFinding] = []
    cleared = 0
    for file in _load_film_files(session):
        size = file.size or 0
        if 0 < size < SMALL_FILE_BYTES:
            small = _small_file_finding(file=file, baselines=baselines)
            if small is None:
                cleared += 1
            else:
                findings.append(small)
            continue

        verdict = bitrate.judge(
            size=file.size,
            duration_ms=file.duration_ms,
            resolution=file.resolution,
            codec=file.video_codec,
            baselines=baselines,
        )
        if verdict is None or not verdict.bloated:
            continue
        saving = bitrate.reencode_saving(
            size=file.size,
            duration_ms=file.duration_ms,
            resolution=file.resolution,
            from_codec=file.video_codec,
            baselines=baselines,
        )
        findings.append(
            SizeFinding(
                tmdb_id=file.tmdb_id,
                title=file.title,
                year=file.year,
                kind="oversized",
                path=file.path,
                size=size,
                duration_ms=file.duration_ms,
                runtime_minutes=file.runtime,
                resolution=file.resolution,
                video_codec=file.video_codec,
                bytes_reclaimable=max(verdict.excess, saving),
                reasons=[
                    f"{_fmt_gb(size)} at {file.resolution or 'unknown'}, "
                    f"{verdict.ratio:.1f}× the usual rate",
                    f"about {_fmt_gb(verdict.excess)} more than its peers",
                ],
            )
        )

    findings.sort(key=lambda f: (-f.bytes_reclaimable, f.tmdb_id, f.path or ""))
    return OutlierReport(
        findings=findings[: max(1, limit)],
        total_reclaimable=sum(f.bytes_reclaimable for f in findings),
        oversized_count=sum(1 for f in findings if f.kind == "oversized"),
        truncated_count=sum(1 for f in findings if f.kind == "truncated"),
        bad_rip_count=sum(1 for f in findings if f.kind == "bad_rip"),
        short_films_cleared=cleared,
    )
