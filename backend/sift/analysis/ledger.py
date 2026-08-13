"""One queue, one currency, one ordering.

Five separate reports leave you to work out which to act on first, and the answer
is never obvious from any one of them: a hundred duplicated SD episodes and a
single bloated 4K film are not comparable until both are expressed as the disk
they would return. So every finding converts to the same figure — estimated bytes
reclaimable — and lands in one list.

**The ordering is the substance of this module, not the ranking.** Findings carry
a risk tier, and the tiers are worked in order:

* **Tier 0 — nothing of value is lost.** Duplicate copies, samples and trailers
  imported as the feature, truncated downloads. There is no quality judgement to
  make, because the thing being removed is not the thing you wanted.
* **Tier 1 — reversible.** Re-encodes, where the original survives until the
  replacement is verified.
* **Tier 2 — a judgement call.** Quality downgrades. Irreversible without
  re-acquiring the title.

Most of the disk comes back at tier 0, before a single question of taste is
asked. A list sorted purely by size would interleave the three and invite the
riskiest action first, which is how a tool like this loses someone's library.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..db.models import MediaFile, Show
from . import bitrate, duplicates, outliers, suitability, tv_duplicates, tv_size

TIER_FREE = 0
TIER_REVERSIBLE = 1
TIER_JUDGEMENT = 2

TIER_LABELS = {
    TIER_FREE: "Nothing is lost",
    TIER_REVERSIBLE: "Reversible",
    TIER_JUDGEMENT: "A judgement call",
}


@dataclass(frozen=True)
class Finding:
    kind: str
    target_kind: str  # movie | show | season
    target_id: str
    title: str
    detail: str
    bytes_reclaimable: int
    risk_tier: int
    reasons: list[str]

    @property
    def reversible(self) -> bool:
        return self.risk_tier <= TIER_REVERSIBLE


@dataclass(frozen=True)
class Ledger:
    findings: list[Finding]
    total_reclaimable: int
    by_tier: dict[int, int]
    counts_by_tier: dict[int, int]


@dataclass(frozen=True)
class Step:
    finding: Finding
    running_total: int


@dataclass(frozen=True)
class Plan:
    """The cheapest set of actions that reaches a target."""

    target_bytes: int
    steps: list[Step]
    reached: bool
    total: int
    # Highest risk tier the plan had to reach into. Zero means the target was met
    # without asking a single question of taste.
    highest_tier: int


def _show_facts(show: Show) -> suitability.ShowFacts:
    return suitability.ShowFacts(
        title=show.title,
        genres=list(show.genres or []),
        keywords=list(show.keywords or []),
        original_language=show.original_language,
        runtime=show.runtime,
        is_kids=show.is_kids,
        plays=show.plays or 0,
        mean_completion=show.mean_completion,
        last_played_at=show.last_played_at,
        typical_stream_height=show.typical_stream_height,
    )


def _fmt(value: int) -> str:
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f} TB"
    return f"{value / 1_000_000_000:.1f} GB"


def build(session: Session, *, limit: int = 500) -> Ledger:
    """Every finding, in one currency, ordered by tier then by size."""
    findings: list[Finding] = []
    baselines = outliers.load_baselines(session)

    # --- tier 0: duplicates, both kinds -------------------------------------
    film_groups, _surplus = duplicates.find(session, limit=1000)
    sizes = _movie_copy_sizes(session)
    for group in film_groups:
        keys = [c.rating_key for c in group.copies]
        known = sorted((sizes.get(k, 0) for k in keys), reverse=True)
        reclaimable = sum(known[1:])
        if reclaimable <= 0:
            continue
        findings.append(
            Finding(
                kind="duplicate_movie",
                target_kind="movie",
                target_id=str(group.tmdb_id),
                title=group.title,
                detail=f"{len(group.copies)} copies, {group.surplus} could go",
                bytes_reclaimable=reclaimable,
                risk_tier=TIER_FREE,
                reasons=["the film survives either way — only the surplus copies go"],
            )
        )

    show_dupes, _total = tv_duplicates.find(session, limit=1000)
    for show in show_dupes:
        if show.reclaimable <= 0:
            continue
        findings.append(
            Finding(
                kind="duplicate_episodes",
                target_kind="show",
                target_id=str(show.tvdb_id),
                title=show.title,
                detail=f"{len(show.episodes)} episodes held twice, {show.surplus} files could go",
                bytes_reclaimable=show.reclaimable,
                risk_tier=TIER_FREE,
                reasons=["every episode survives — split files are excluded"],
            )
        )

    # --- tier 0 and 1: film size outliers -----------------------------------
    report = outliers.find(session, limit=1000)
    for item in report.findings:
        if item.bytes_reclaimable <= 0:
            continue
        findings.append(
            Finding(
                kind=item.kind,
                target_kind="movie",
                target_id=str(item.tmdb_id),
                title=item.title,
                detail=(
                    "not the film you wanted"
                    if item.kind == "truncated"
                    else f"{_fmt(item.size)} at {item.resolution or 'unknown'}"
                ),
                bytes_reclaimable=item.bytes_reclaimable,
                risk_tier=TIER_FREE if item.kind == "truncated" else TIER_REVERSIBLE,
                reasons=list(item.reasons),
            )
        )

    # --- tier 1: heavy seasons ----------------------------------------------
    sized, _excess = tv_size.seasons(session, baselines=baselines, limit=1000)
    for season in sized:
        if not season.bloated or season.excess <= 0:
            continue
        findings.append(
            Finding(
                kind="oversized_season",
                target_kind="season",
                target_id=f"{season.tvdb_id}:{season.season_number}",
                title=f"{season.title} — season {season.season_number}",
                detail=(
                    f"{_fmt(season.total_bytes)} over {season.episode_count} episodes "
                    f"at {season.resolution or 'unknown'}"
                ),
                bytes_reclaimable=season.excess,
                risk_tier=TIER_REVERSIBLE,
                reasons=[
                    f"{_fmt(int(season.bytes_per_hour))} per hour, "
                    "well above others of its kind"
                ],
            )
        )

    # --- tier 2: quality downgrades -----------------------------------------
    findings.extend(_downgrades(session, baselines))

    findings.sort(key=lambda f: (f.risk_tier, -f.bytes_reclaimable))
    by_tier: dict[int, int] = {}
    counts: dict[int, int] = {}
    for finding in findings:
        by_tier[finding.risk_tier] = by_tier.get(finding.risk_tier, 0) + finding.bytes_reclaimable
        counts[finding.risk_tier] = counts.get(finding.risk_tier, 0) + 1
    return Ledger(
        findings=findings[: max(1, limit)],
        total_reclaimable=sum(f.bytes_reclaimable for f in findings),
        by_tier=by_tier,
        counts_by_tier=counts,
    )


def _movie_copy_sizes(session: Session) -> dict[str, int]:
    """Bytes behind each Plex copy, so a duplicate's cost is real rather than assumed."""
    from sqlalchemy import select

    sizes: dict[str, int] = {}
    for rating_key, size in session.execute(
        select(MediaFile.rating_key, MediaFile.size).where(MediaFile.rating_key.is_not(None))
    ):
        if rating_key:
            sizes[rating_key] = sizes.get(rating_key, 0) + (size or 0)
    return sizes


def _downgrades(session: Session, baselines: bitrate.Baselines) -> list[Finding]:
    """Seasons held higher than they need to be, where every signal agrees.

    Reads through the shared season loader rather than repeating the four-table
    join, which was previously executed once here and twice more in ``tv_size``.
    """
    grouped = tv_size.load_seasons(session)
    shows = tv_size.load_shows(session)

    out: list[Finding] = []
    for (tvdb_id, number), group in grouped.items():
        files = group.files
        show = shows[tvdb_id]
        resolutions = [f.resolution for f in files if f.resolution]
        if not resolutions:
            continue
        current = max(set(resolutions), key=resolutions.count)
        verdict = suitability.assess(
            _show_facts(show),
            season_number=number,
            air_year=group.air_year,
            current=current,
            has_uhd_file=any(f.resolution == "2160p" for f in files),
        )
        if verdict.verdict != "downgrade" or verdict.target is None:
            continue
        total_bytes = sum(f.size or 0 for f in files)
        total_ms = sum(f.duration_ms or 0 for f in files)
        target_bucket = baselines.bucket(verdict.target, _dominant_codec(files))
        if target_bucket is None or not total_ms:
            continue
        expected = target_bucket.median_rate * (total_ms / 3_600_000)
        saving = max(0, int(round(total_bytes - expected)))
        if saving <= 0:
            continue
        out.append(
            Finding(
                kind="quality_downgrade",
                target_kind="season",
                target_id=f"{tvdb_id}:{number}",
                title=f"{show.title} — season {number}",
                detail=f"{current} today, {verdict.target} would do",
                bytes_reclaimable=saving,
                risk_tier=TIER_JUDGEMENT,
                reasons=list(verdict.reasons),
            )
        )
    return out


def _dominant_codec(files: list[tv_size.SeasonFile]) -> str | None:
    codecs = [f.video_codec for f in files if f.video_codec]
    return max(set(codecs), key=codecs.count) if codecs else None


def plan(ledger: Ledger, target_bytes: int) -> Plan:
    """The cheapest way to reach a target, safest actions first.

    Cheapest is measured in regret, not in effort: the walk exhausts every
    zero-loss finding before touching a reversible one, and every reversible one
    before asking a question of taste. Sorting the whole list by size instead
    would routinely propose deleting something irreplaceable while a duplicate
    sat untouched further down.
    """
    steps: list[Step] = []
    running = 0
    highest = TIER_FREE
    for tier in (TIER_FREE, TIER_REVERSIBLE, TIER_JUDGEMENT):
        if running >= target_bytes:
            break
        tier_findings = sorted(
            (f for f in ledger.findings if f.risk_tier == tier),
            key=lambda f: f.bytes_reclaimable,
            reverse=True,
        )
        for finding in tier_findings:
            if running >= target_bytes:
                break
            running += finding.bytes_reclaimable
            highest = tier
            steps.append(Step(finding=finding, running_total=running))
    return Plan(
        target_bytes=target_bytes,
        steps=steps,
        reached=running >= target_bytes,
        total=running,
        highest_tier=highest if steps else TIER_FREE,
    )
