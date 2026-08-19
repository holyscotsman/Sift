"""Resumable ingestion pipeline.

A scan runs a fixed sequence of phases: read the Plex catalog (the library
authority), read the Radarr catalog, pull Tautulli history, grab TMDB metadata,
finalize the snapshot, score the library, then an advisory AI analysis. Each phase
records a checkpoint in ``scan_runs.checkpoints`` the moment it finishes, so an
interrupted remote scan resumes exactly where it stopped and a re-run is idempotent
(all writes are upserts). Network I/O is async; the sync snapshot writes are
marshalled onto a worker thread so the event loop stays free.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import junk
from ..analysis import recommend as recommend_analysis
from ..clients.plex import EPISODE as PLEX_EPISODE
from ..clients.plex import SHOW as PLEX_SHOW
from ..clients.plex import PlexClient
from ..clients.radarr import RadarrClient
from ..clients.sonarr import SonarrClient
from ..clients.tautulli import TautulliClient
from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import (
    Collection,
    CollectionMember,
    Episode,
    MediaFile,
    Movie,
    MoviePerson,
    Person,
    PlexCopy,
    Rating,
    RatingSource,
    ScanRun,
    ScanStatus,
    Season,
    Show,
    WatchHistory,
    utcnow,
)
from . import normalize
from . import sections as section_plan

log = logging.getLogger("sift.ingest")

PHASES = (
    "preflight",
    "plex",
    "radarr",
    "sonarr",
    "tautulli",
    "tmdb",
    "finalize",
    "score",
    "ai",
)

# A configured service that doesn't answer this fast is treated as down for the run.
# Generous enough for a cold Plex behind a slow tunnel, short enough that a dead
# optional service (Tautulli is the usual one) costs seconds, not the whole scan.
PREFLIGHT_TIMEOUT_SECONDS = 15.0

# Episodes are written every this many records rather than all at once. A large
# TV library is tens of thousands of episodes carrying full media metadata, and
# holding the lot before the first write is what gets a scan killed for memory on
# a small host — which leaves the run marked running forever and reads as a scan
# frozen at the same percentage.
EPISODE_BATCH = 2000

# The same rule for the Sonarr phase, counted in shows because that is the unit it
# reads. Smaller than EPISODE_BATCH because a show is not one record: it carries
# every episode and every file Sonarr knows about, so 25 long-running series is
# already the same order of magnitude.
SERIES_BATCH = 25

# Ceiling on the advisory AI pass. It's the last phase and reviews candidates one at
# a time, so without a bound a slow provider parks a finished scan on "AI analysis"
# for minutes. Whatever is done by then is kept.
AI_BUDGET_SECONDS = 120.0

# Canon entries resolved to TMDB ids per scan. The canon arrives keyed by IMDb id
# and cannot be compared with the library until it is reconciled, but ten thousand
# lookups against a rate-limited API is not something to do while a scan is
# waiting. At this rate the list resolves over roughly twenty-five scans, and the
# coverage figure says so rather than pretending to be complete.
CANON_RESOLVE_BUDGET = 400


@dataclass
class ScanProgress:
    scan_run_id: int
    phase: str
    phase_index: int
    total_phases: int
    status: str  # running | done | skipped | error
    message: str = ""
    counts: dict[str, int] = field(default_factory=dict)


ProgressCallback = Callable[[ScanProgress], Awaitable[None]]


class ScanPipeline:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        radarr: RadarrClient | None = None,
        plex: PlexClient | None = None,
        sonarr: SonarrClient | None = None,
        tautulli: TautulliClient | None = None,
        tmdb: TmdbClient | None = None,
        progress_cb: ProgressCallback | None = None,
        tmdb_enrich_limit: int = 0,
    ) -> None:
        self.factory = session_factory
        self.settings = settings
        self.radarr = radarr
        self.plex = plex
        self.sonarr = sonarr
        self.tautulli = tautulli
        self.tmdb = tmdb
        self.progress_cb = progress_cb
        self.tmdb_enrich_limit = tmdb_enrich_limit
        # Filled by the preflight phase; named in its progress message.
        self.skipped_services: list[str] = []
        self._progress_at: tuple[int, str, int] | None = None

    # ---------------------------------------------------------------- orchestration

    async def run(self, scan_run_id: int, *, resume: bool = False) -> ScanRun:
        checkpoints = await asyncio.to_thread(self._load_checkpoints, scan_run_id)
        stats: dict[str, int] = {}
        try:
            for index, phase in enumerate(PHASES):
                # Preflight always re-runs: reachability is a fact about right now,
                # not something a previous run's checkpoint can vouch for.
                resumable = phase != "preflight"
                if resume and resumable and checkpoints.get(phase, {}).get("status") == "done":
                    await self._emit(scan_run_id, phase, index, "skipped", "already complete")
                    stats.update(checkpoints[phase].get("counts", {}))
                    continue
                await self._emit(scan_run_id, phase, index, "running")
                # Remembered so a long phase can report its own progress; without
                # it a twenty-minute sweep and a dead process look identical.
                self._progress_at = (scan_run_id, phase, index)
                counts = await getattr(self, f"_phase_{phase}")()
                stats.update(counts)
                await asyncio.to_thread(self._save_phase, scan_run_id, phase, counts)
                await self._emit(
                    scan_run_id, phase, index, "done", self._phase_note(phase), counts=counts
                )
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised
            log.warning("scan %s interrupted during a phase: %s", scan_run_id, exc)
            await asyncio.to_thread(
                self._finish, scan_run_id, ScanStatus.INTERRUPTED, stats, str(exc)
            )
            raise
        return await asyncio.to_thread(
            self._finish, scan_run_id, ScanStatus.COMPLETED, stats, None
        )

    def _phase_note(self, phase: str) -> str:
        """Human-facing detail for a finished phase — currently only preflight has
        something worth saying, and only when it dropped a service."""
        if phase == "preflight" and self.skipped_services:
            return f"skipped (not responding): {', '.join(self.skipped_services)}"
        return ""

    async def _emit(
        self,
        scan_run_id: int,
        phase: str,
        index: int,
        status: str,
        message: str = "",
        counts: dict[str, int] | None = None,
    ) -> None:
        if self.progress_cb is None:
            return
        await self.progress_cb(
            ScanProgress(scan_run_id, phase, index, len(PHASES), status, message, counts or {})
        )

    async def _note(
        self,
        message: str,
        counts: dict[str, int] | None = None,
        *,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        """Say what a long phase is doing while it does it.

        ``done``/``total`` are how far through the phase itself we are, sent as
        ``phase_done``/``phase_total`` in the counts. The dial is otherwise driven
        by the phase index alone, so it cannot move until a phase ends — and the
        Plex phase is by far the longest, which is why a large library sits on one
        frozen number long enough to look crashed.

        Only sent where a real denominator exists. An invented one that reaches 90%
        and stops is worse than a number that never moves, because it also lies.
        """
        if self._progress_at is None:
            return
        scan_run_id, phase, index = self._progress_at
        payload = dict(counts or {})
        if done is not None and total:
            payload["phase_done"] = done
            payload["phase_total"] = total
        await self._emit(scan_run_id, phase, index, "running", message, counts=payload)

    # ---------------------------------------------------------------------- phases

    async def _phase_preflight(self) -> dict[str, int]:
        """Probe every configured service and drop the ones that don't answer.

        Without this a service that is saved but unreachable — a Tautulli that moved,
        a Plex behind a dead tunnel — raises inside its phase and takes the entire
        scan down with it, so a working Radarr never gets read. Dropping the client
        turns that phase into the no-op it already is when the service isn't
        configured, and the rest of the scan completes normally.

        Each probe is hard-bounded: ``health()`` retries internally, so the timeout
        goes on the outside where it can actually cap the wait.
        """
        skipped: list[str] = []
        for name in ("plex", "radarr", "sonarr", "tautulli", "tmdb"):
            client = getattr(self, name)
            if client is None:
                continue
            try:
                status = await asyncio.wait_for(
                    client.health(), timeout=PREFLIGHT_TIMEOUT_SECONDS
                )
                reachable = status.ok
                detail = status.detail
            except TimeoutError:
                reachable, detail = False, f"no answer in {PREFLIGHT_TIMEOUT_SECONDS:.0f}s"
            except Exception as exc:  # noqa: BLE001 - any failure means "not usable now"
                reachable, detail = False, str(exc)
            if not reachable:
                log.info("preflight: skipping %s this scan (%s)", name, detail)
                setattr(self, name, None)
                skipped.append(name)
        self.skipped_services = skipped
        ready = sum(
            1
            for n in ("plex", "radarr", "sonarr", "tautulli", "tmdb")
            if getattr(self, n) is not None
        )
        return {"services_ready": ready, "services_skipped": len(skipped)}

    async def _phase_radarr(self) -> dict[str, int]:
        if self.radarr is None:
            return {}
        movies = await self.radarr.get_movies()
        collections = await self.radarr.get_collections()
        normalized = [normalize.normalize_radarr_movie(m) for m in movies]
        normalized_collections = [normalize.normalize_radarr_collection(c) for c in collections]
        return await asyncio.to_thread(
            self._persist_radarr, normalized, normalized_collections
        )

    async def _phase_plex(self) -> dict[str, int]:
        if self.plex is None:
            return {}
        kids = {s.lower() for s in self.settings.plex.kids_sections}
        sections = await self.plex.get_sections()
        items: list[dict[str, Any]] = []
        shows: list[dict[str, Any]] = []
        episode_count = 0
        file_count = 0
        # Taken before the first episode write; everything written after it is
        # stamped later, so what stays behind the line is what disappeared.
        sweep_from = utcnow()
        swept_tv = False
        plans = section_plan.plan(sections, self.settings.plex.section_kinds)
        for plan in plans:
            if not plan.scanned:
                log.info("skipping Plex library %r — %s", plan.title, plan.reason)
                continue
            kind = plan.kind
            title = plan.title
            is_kids = title.lower() in kids
            await self._note(f"reading {title}")
            if kind == "movie":
                async for batch in self.plex.iter_section_items(plan.key):
                    for raw in batch:
                        items.append(
                            normalize.normalize_plex_item(raw, section_title=title, is_kids=is_kids)
                        )
            elif kind == "show":
                # Two passes over the section. Shows carry the TVDB guid that keys
                # them to Sonarr; episodes carry the files. Shows are persisted
                # first so the episode sweep has something to attach to.
                section_shows = [
                    show
                    for show in (
                        normalize.normalize_plex_show(raw, section_title=title, is_kids=is_kids)
                        for raw in await self.plex.get_section_items(
                            plan.key, item_type=PLEX_SHOW
                        )
                    )
                    if show is not None
                ]
                shows.extend(section_shows)
                await asyncio.to_thread(self._persist_plex_shows, section_shows)
                swept_tv = True

                # Streamed and written as it arrives. See EPISODE_BATCH.
                pending: list[dict[str, Any]] = []
                async for batch in self.plex.iter_section_items(
                    plan.key, item_type=PLEX_EPISODE
                ):
                    for raw in batch:
                        episode = normalize.normalize_plex_episode(raw)
                        if episode is not None:
                            pending.append(episode)
                    if len(pending) >= EPISODE_BATCH:
                        written = await asyncio.to_thread(self._persist_plex_episodes, pending)
                        episode_count += written["plex_episodes"]
                        file_count += written["plex_episode_files"]
                        pending = []
                        await self._note(
                            f"{title}: {episode_count:,} episodes",
                            {"plex_episodes": episode_count},
                            done=episode_count,
                            total=self.plex.last_section_total or None,
                        )
                if pending:
                    written = await asyncio.to_thread(self._persist_plex_episodes, pending)
                    episode_count += written["plex_episodes"]
                    file_count += written["plex_episode_files"]

        # Only once every TV section has been read. Run any earlier and a copy
        # that simply hadn't been reached yet would be mistaken for a deleted one.
        if swept_tv:
            await asyncio.to_thread(self._sweep_plex_episode_media, sweep_from)

        await self._note("saving the film catalog")
        counts = await asyncio.to_thread(self._persist_plex, items)
        if shows or episode_count:
            counts.update(
                {
                    "plex_shows": len(shows),
                    "plex_episodes": episode_count,
                    "plex_episode_files": file_count,
                }
            )
        return counts

    def _sweep_sonarr_episode_media(self, cutoff: datetime) -> int:
        """The Sonarr-side sweep, on its own connection because the batched writes
        that preceded it each closed theirs."""
        with self.factory() as session:
            dropped = self._sweep_episode_media(session, cutoff, source="sonarr")
            session.commit()
        return dropped

    def _sweep_plex_episode_media(self, cutoff: datetime) -> int:
        """The Plex-side sweep, on its own connection because the streamed writes
        that preceded it each closed theirs."""
        with self.factory() as session:
            dropped = self._sweep_episode_media(session, cutoff, source="plex")
            session.commit()
        return dropped

    def _persist_plex_tv(
        self, shows: list[dict[str, Any]], episodes: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Shows and episodes together. Kept for callers that have both to hand."""
        counts = self._persist_plex_shows(shows)
        counts.update(self._persist_plex_episodes(episodes))
        return counts

    def _persist_plex_shows(self, shows: list[dict[str, Any]]) -> dict[str, int]:
        """Record what Plex holds for TV, and every file behind it.

        Sonarr describes one file per episode, which is the right answer to "what
        should be there" and the wrong one for "what is actually on disk". Plex
        reports every copy it can see, so this is what makes a duplicated episode
        visible at all — the same reason ``plex_copies`` exists for films.
        """
        with self.factory() as session:
            # Scoped to the shows in hand, like every other preload in this file.
            # Called once per TV library section rather than per batch, so reading
            # the whole table was linear rather than quadratic — but a library with
            # several sections still re-read every show for each one, and the rule
            # is easier to keep than to remember the exception to.
            wanted = sorted({data["tvdb_id"] for data in shows if data.get("tvdb_id")})
            existing: dict[int, Show] = {}
            for start in range(0, len(wanted), 500):
                for row in session.scalars(
                    select(Show).where(Show.tvdb_id.in_(wanted[start : start + 500]))
                ):
                    existing[row.tvdb_id] = row
            by_rating_key: dict[str, Show] = {}
            for data in shows:
                tvdb_id = data["tvdb_id"]
                show = existing.get(tvdb_id)
                if show is None:
                    show = Show(tvdb_id=tvdb_id, title=data["title"])
                    session.add(show)
                    existing[tvdb_id] = show
                # Presence in a Plex show section IS library membership, exactly
                # as for films.
                show.in_plex = True
                show.plex_rating_key = data["plex_rating_key"]
                show.library_section = data["library_section"]
                show.is_kids = data["is_kids"]
                show.title = show.title or data["title"]
                show.year = show.year if show.year is not None else data["year"]
                show.tmdb_id = show.tmdb_id or data["tmdb_id"]
                if data["plex_rating_key"]:
                    by_rating_key[data["plex_rating_key"]] = show
            session.commit()
        return {"plex_shows": len(shows)}

    def _persist_plex_episodes(self, episodes: list[dict[str, Any]]) -> dict[str, int]:
        """One batch of episodes and the files behind them.

        Called repeatedly as pages arrive rather than once with everything, so a
        large TV library is written as it is read instead of being held whole in
        memory first. Shows must already be persisted — they are, because the
        show pass runs before the episode sweep for each section.
        """
        if not episodes:
            return {"plex_episodes": 0, "plex_episode_files": 0}
        with self.factory() as session:
            # Every preload here is scoped to this batch, and that is the whole
            # point. Read whole, these three are a full hydration of the shows,
            # seasons and episodes table *per batch* — so batch 15 of a 30,000
            # episode library re-reads 28,000 rows to write 2,000, and the scan
            # gets steadily slower until it looks stopped. Quadratic work is worse
            # than the memory problem batching was introduced to solve.
            wanted_keys = sorted({e["show_rating_key"] for e in episodes if e["show_rating_key"]})
            by_rating_key: dict[str, Show] = {}
            for start in range(0, len(wanted_keys), 500):
                for row in session.scalars(
                    select(Show).where(Show.plex_rating_key.in_(wanted_keys[start : start + 500]))
                ):
                    if row.plex_rating_key:
                        by_rating_key[row.plex_rating_key] = row

            show_ids = sorted({s.tvdb_id for s in by_rating_key.values()})
            seasons: dict[tuple[int, int], Season] = {}
            for start in range(0, len(show_ids), 500):
                for season_row in session.scalars(
                    select(Season).where(Season.show_id.in_(show_ids[start : start + 500]))
                ):
                    seasons[(season_row.show_id, season_row.season_number)] = season_row

            season_ids = sorted({s.id for s in seasons.values() if s.id is not None})
            known: dict[tuple[int, int], Episode] = {}
            for start in range(0, len(season_ids), 500):
                for episode_row in session.scalars(
                    select(Episode).where(Episode.season_id.in_(season_ids[start : start + 500]))
                ):
                    known[(episode_row.season_id, episode_row.episode_number)] = episode_row

            records: list[tuple[Episode, dict[str, Any]]] = []
            written = 0
            for data in episodes:
                show = by_rating_key.get(data["show_rating_key"])
                if show is None:
                    # An episode whose show carried no TVDB guid. Filing it under a
                    # guessed show would group unrelated files together, which is
                    # exactly the mistake duplicate detection must not make.
                    continue
                key = (show.tvdb_id, data["season_number"])
                season = seasons.get(key)
                if season is None:
                    season = Season(show_id=show.tvdb_id, season_number=data["season_number"])
                    session.add(season)
                    session.flush()
                    seasons[key] = season
                episode_key = (season.id, data["episode_number"])
                episode = known.get(episode_key)
                if episode is None:
                    episode = Episode(season_id=season.id, episode_number=data["episode_number"])
                    session.add(episode)
                    known[episode_key] = episode
                episode.title = episode.title or data["title"]
                episode.plex_rating_key = data["plex_rating_key"]
                if data["media_files"]:
                    episode.has_file = True
                written += 1
                for record in data["media_files"]:
                    records.append((episode, record))
            session.flush()
            files = self._sync_episode_media(session, records, source="plex")
            # Plex has spoken for these episodes, so Sonarr's view of the same
            # files must not be counted alongside its own.
            superseded = [e.id for e, _ in records if e.id is not None]
            for start in range(0, len(superseded), 500):
                session.execute(
                    delete(MediaFile).where(
                        MediaFile.episode_id.in_(superseded[start : start + 500]),
                        MediaFile.source != "plex",
                    )
                )
            session.commit()
        return {"plex_episodes": written, "plex_episode_files": files}

    async def _phase_sonarr(self) -> dict[str, int]:
        """Read the TV catalog: the shows, their seasons, and what backs each episode.

        One request returns every series with per-season ``sizeOnDisk``, which is
        already enough to rank shows by weight. The per-series calls that follow
        are what make the finer questions answerable — ``episodeFileId`` is the
        exact test for a multi-episode file, and the file records carry the media
        detail the bitrate baselines need.
        """
        if self.sonarr is None:
            return {}
        # Before the first write, so every row this phase touches stamps later and
        # only what nothing reported is left behind the line.
        sweep_from = utcnow()
        raw_series = await self.sonarr.get_series()
        series = [
            s for s in (normalize.normalize_sonarr_series(r) for r in raw_series) if s is not None
        ]
        await self._note(f"reading {len(series):,} shows from Sonarr")

        totals = {"sonarr_shows": 0, "sonarr_episodes": 0, "sonarr_media_files": 0}
        pending: list[dict[str, Any]] = []
        detail: dict[int, dict[str, Any]] = {}

        async def flush() -> None:
            """Write what has been read, then let it go.

            Two calls per show, each returning every episode and every file it has,
            is the largest payload in the whole scan. Holding all of it to write
            once is how the Plex phase died; there is no reason to expect this one
            to survive what that didn't.
            """
            if not pending:
                return
            written = await asyncio.to_thread(self._persist_sonarr, list(pending), dict(detail))
            for key, value in written.items():
                totals[key] = totals.get(key, 0) + value
            pending.clear()
            detail.clear()
            await self._note(
                f"{totals['sonarr_shows']:,} of {len(series):,} shows",
                {"sonarr_episodes": totals["sonarr_episodes"]},
            )

        for show in series:
            pending.append(show)
            sonarr_id = show["sonarr_id"]
            if sonarr_id:
                episodes = [
                    e
                    for e in (
                        normalize.normalize_sonarr_episode(r)
                        for r in await self.sonarr.get_episodes(sonarr_id)
                    )
                    if e is not None
                ]
                files = [
                    f
                    for f in (
                        normalize.normalize_sonarr_episode_file(r)
                        for r in await self.sonarr.get_episode_files(sonarr_id)
                    )
                    if f is not None
                ]
                detail[show["tvdb_id"]] = {"episodes": episodes, "files": files}
            if len(pending) >= SERIES_BATCH:
                await flush()
        await flush()

        # Once, with every show accounted for.
        await asyncio.to_thread(self._sweep_sonarr_episode_media, sweep_from)
        return totals

    def _persist_sonarr(
        self, series: list[dict[str, Any]], detail: dict[int, dict[str, Any]]
    ) -> dict[str, int]:
        """Persist a slice of the TV catalog: shows, seasons, episodes and files.

        Takes a slice rather than the library because the caller streams (see
        :data:`SERIES_BATCH`). Every preload here is therefore scoped to the shows
        in hand: reading every season and every episode in the database was
        affordable when this ran once, and is a full-table hydration per batch once
        it runs many times.
        """
        with self.factory() as session:
            tvdb_ids = [s["tvdb_id"] for s in series]
            shows: dict[int, Show] = {}
            for start in range(0, len(tvdb_ids), 500):
                batch = tvdb_ids[start : start + 500]
                for show_row in session.scalars(select(Show).where(Show.tvdb_id.in_(batch))):
                    shows[show_row.tvdb_id] = show_row
            seasons: dict[tuple[int, int], Season] = {}
            for start in range(0, len(tvdb_ids), 500):
                batch = tvdb_ids[start : start + 500]
                for season_row in session.scalars(
                    select(Season).where(Season.show_id.in_(batch))
                ):
                    seasons[(season_row.show_id, season_row.season_number)] = season_row
            season_ids = sorted({s.id for s in seasons.values() if s.id is not None})
            episodes: dict[tuple[int, int], Episode] = {}
            for start in range(0, len(season_ids), 500):
                for episode_row in session.scalars(
                    select(Episode).where(Episode.season_id.in_(season_ids[start : start + 500]))
                ):
                    episodes[(episode_row.season_id, episode_row.episode_number)] = episode_row

            episode_count = 0
            file_records: list[tuple[Episode, dict[str, Any]]] = []
            for data in series:
                tvdb_id = data["tvdb_id"]
                show = shows.get(tvdb_id)
                if show is None:
                    show = Show(tvdb_id=tvdb_id, title=data["title"])
                    session.add(show)
                    shows[tvdb_id] = show
                show.tmdb_id = data["tmdb_id"] or show.tmdb_id
                show.sonarr_id = data["sonarr_id"]
                show.title = data["title"] or show.title
                show.year = data["year"] if data["year"] is not None else show.year
                show.status = data["status"]
                show.network = data["network"]
                show.genres = data["genres"]
                show.runtime = data["runtime"]
                show.monitored = data["monitored"]
                show.quality_profile_id = data["quality_profile_id"]

                found = detail.get(tvdb_id, {})
                files_by_id = {
                    f["sonarr_episode_file_id"]: f for f in found.get("files", [])
                }
                # Grouped once. Walking the whole episode list per season is
                # quadratic in a way that only shows up on the long-running shows
                # this feature exists for: 20 seasons of 500 episodes is 10,000
                # comparisons to place 500 rows.
                by_season: dict[int, list[dict[str, Any]]] = {}
                # Air year is taken per season from the episodes themselves. The
                # series payload carries only one year, and a show's first year is
                # the wrong ceiling for its later seasons — Scrubs began in 2001
                # and ended in HD.
                years: dict[int, list[int]] = {}
                for episode_data in found.get("episodes", []):
                    by_season.setdefault(episode_data["season_number"], []).append(episode_data)
                    if episode_data["air_date"]:
                        years.setdefault(episode_data["season_number"], []).append(
                            episode_data["air_date"].year
                        )

                for season_data in data["seasons"]:
                    number = season_data["season_number"]
                    season = seasons.get((tvdb_id, number))
                    if season is None:
                        season = Season(show_id=tvdb_id, season_number=number)
                        session.add(season)
                        session.flush()  # need the id to hang episodes off
                        seasons[(tvdb_id, number)] = season
                    season.size_on_disk = season_data["size_on_disk"]
                    season.episode_count = season_data["episode_count"]
                    season.episode_file_count = season_data["episode_file_count"]
                    season_years = years.get(number)
                    season.air_year = min(season_years) if season_years else season.air_year

                    for episode_data in by_season.get(number, ()):
                        key = (season.id, episode_data["episode_number"])
                        episode = episodes.get(key)
                        if episode is None:
                            episode = Episode(
                                season_id=season.id,
                                episode_number=episode_data["episode_number"],
                            )
                            session.add(episode)
                            episodes[key] = episode
                        episode.title = episode_data["title"]
                        episode.air_date = episode_data["air_date"]
                        episode.sonarr_episode_id = episode_data["sonarr_episode_id"]
                        episode.sonarr_episode_file_id = episode_data["sonarr_episode_file_id"]
                        episode.has_file = episode_data["has_file"]
                        episode_count += 1
                        record = files_by_id.get(episode_data["sonarr_episode_file_id"])
                        if record is not None:
                            file_records.append((episode, record))
            session.flush()
            # No sweep here. This is one slice of the catalog, and a delete decided
            # from a slice removes everything the other slices hold — see
            # _sync_episode_media. The phase sweeps once, at the end.
            files = self._sync_episode_media(session, file_records, source="sonarr")
            session.commit()
        return {
            "sonarr_shows": len(series),
            "sonarr_episodes": episode_count,
            "sonarr_media_files": files,
        }

    def _sync_episode_media(
        self,
        session: Session,
        records: list[tuple[Episode, dict[str, Any]]],
        *,
        source: str,
        sweep_from: datetime | None = None,
    ) -> int:
        """Reconcile ``media_files`` for episodes, from one source.

        Identity is the **path**, not the episode. A single "S01E01-E02" file is
        one file on disk that two episodes both point at, so keying on the episode
        would store it twice and report double the space it occupies. It is
        recorded once, against the first episode it covers.

        Writing marks rows with ``seen_at``; removing what is no longer on disk is
        a separate sweep (see :meth:`_sweep_episode_media`). ``sweep_from`` runs it
        inline for callers that pass the whole library in one go. It must stay
        opt-in: episodes arrive in batches, and *any* delete rule evaluated against
        a single batch gets a duplicated episode wrong. Scoping to the batch's own
        episodes looks safe and isn't — the second copy of an episode routinely
        lands in a later batch than the first, and would take the first with it,
        quietly deleting exactly the evidence the duplicate report is built on.
        """

        def identity(path: str | None, episode_id: int | None) -> str:
            return path or f"episode:{episode_id}"

        # Only the rows this batch could possibly match. Loading every file for the
        # source was affordable exactly once; now that episodes arrive in batches it
        # would re-read and re-hydrate the whole table for each one, which a
        # file-backed SQLite test cannot feel and a hosted Postgres very much can.
        paths = sorted({p for _episode, record in records if (p := record.get("path"))})
        episode_ids = sorted({e.id for e, _record in records if e.id is not None})
        existing: dict[str, MediaFile] = {}
        for start in range(0, len(paths), 500):
            for row in session.scalars(
                select(MediaFile).where(
                    MediaFile.source == source,
                    MediaFile.episode_id.is_not(None),
                    MediaFile.path.in_(paths[start : start + 500]),
                )
            ):
                existing[identity(row.path, row.episode_id)] = row
        # Rows for a file with no path at all are keyed by episode instead, so they
        # have to be fetched that way or every batch would insert them afresh.
        for start in range(0, len(episode_ids), 500):
            for row in session.scalars(
                select(MediaFile).where(
                    MediaFile.source == source,
                    MediaFile.path.is_(None),
                    MediaFile.episode_id.in_(episode_ids[start : start + 500]),
                )
            ):
                existing[identity(row.path, row.episode_id)] = row

        written = 0
        seen: set[str] = set()
        for episode, record in records:
            payload = {k: v for k, v in record.items() if k != "sonarr_episode_file_id"}
            key = identity(payload.get("path"), episode.id)
            if key in seen:
                continue
            seen.add(key)
            found = existing.get(key)
            if found is None:
                row = MediaFile(episode_id=episode.id, source=source)
                session.add(row)
                existing[key] = row
            else:
                row = found
            for name, value in payload.items():
                setattr(row, name, value)
            row.episode_id = episode.id
            row.seen_at = utcnow()
            written += 1

        if sweep_from is not None:
            self._sweep_episode_media(session, sweep_from, source=source)
        return written

    def _sweep_episode_media(self, session: Session, cutoff: datetime, *, source: str) -> int:
        """Drop episode files this scan never saw — the copy deleted on disk.

        Mark and sweep rather than a set difference, because the marking happens
        across many batches and only the sweep has the whole picture. A row still
        carrying a stamp from before this scan started is one nothing reported
        this time, which is the definition of gone. Rows with no stamp at all
        predate the column and are swept too, or they would be immortal.
        """
        stale = list(
            session.scalars(
                select(MediaFile.id).where(
                    MediaFile.episode_id.is_not(None),
                    MediaFile.source == source,
                    or_(MediaFile.seen_at.is_(None), MediaFile.seen_at < cutoff),
                )
            )
        )
        for start in range(0, len(stale), 500):
            session.execute(delete(MediaFile).where(MediaFile.id.in_(stale[start : start + 500])))
        return len(stale)

    async def _phase_tautulli(self) -> dict[str, int]:
        if self.tautulli is None:
            return {}
        kids_accounts = set(self.settings.tautulli.kids_accounts)

        # Folded page by page rather than collected. History is the one source
        # whose size tracks how much gets *watched* rather than how much is owned,
        # so a heavy household's is larger than its library — and the fold is what
        # the rows were only ever gathered for.
        films: dict[tuple[str, str], dict[str, Any]] = {}
        plays = 0
        async for batch in self.tautulli.iter_history():
            normalize.fold_watch_rows(
                films,
                (normalize.normalize_tautulli_row(r, kids_accounts=kids_accounts) for r in batch),
            )
            plays += len(batch)
            await self._note(f"{plays:,} film plays")
        aggregates = normalize.finalize_watch_rows(films)
        counts = await asyncio.to_thread(self._persist_watch, list(aggregates.values()))

        # Episode history, aggregated per show. This is the evidence behind
        # "how attentively is it actually watched", which is one of the three
        # things that decide whether a show needs to be in HD.
        shows: dict[str, dict[str, Any]] = {}
        episode_plays = 0
        async for batch in self.tautulli.iter_history(media_type="episode"):
            normalize.fold_show_watch(
                shows,
                (
                    row
                    for raw in batch
                    if (row := normalize.normalize_tautulli_episode_row(raw)) is not None
                ),
            )
            episode_plays += len(batch)
            await self._note(f"{episode_plays:,} episode plays")
        finalized = normalize.finalize_show_watch(shows)
        counts.update(await asyncio.to_thread(self._persist_show_watch, list(finalized.values())))
        return counts

    def _persist_show_watch(self, aggregates: list[dict[str, Any]]) -> dict[str, int]:
        """Attach watch aggregates to shows, matched by Plex rating key."""
        if not aggregates:
            return {"show_watch": 0}
        with self.factory() as session:
            by_key = {
                s.plex_rating_key: s
                for s in session.scalars(select(Show).where(Show.plex_rating_key.is_not(None)))
            }
            written = 0
            for data in aggregates:
                show = by_key.get(data["show_rating_key"])
                if show is None:
                    continue
                show.plays = data["plays"]
                show.last_played_at = data["last_played_at"]
                show.mean_completion = data["mean_completion"]
                show.typical_stream_height = data["typical_stream_height"]
                written += 1
            session.commit()
        return {"show_watch": written}

    async def _phase_tmdb(self) -> dict[str, int]:
        if self.tmdb is None:
            return {}
        stats: dict[str, int] = {}
        if self.tmdb_enrich_limit > 0:
            targets = await asyncio.to_thread(self._tmdb_targets, self.tmdb_enrich_limit)
            enriched = []
            for tmdb_id in targets:
                try:
                    # release_dates powers the US-theatrical classifier fact.
                    raw = await self.tmdb.get_movie(
                        tmdb_id, append="keywords,credits,release_dates"
                    )
                except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
                    log.info("tmdb enrich skipped for %s: %s", tmdb_id, exc)
                    continue
                enriched.append(normalize.normalize_tmdb_movie(raw))
            stats.update(await asyncio.to_thread(self._persist_tmdb, enriched))
        stats.update(await self._resolve_curated_lists())
        stats.update(await self._resolve_canon())
        return stats

    async def _resolve_curated_lists(self) -> dict[str, int]:
        """Seed the starter lists, then resolve any titles still lacking a TMDB id."""
        if self.tmdb is None:
            return {}
        pending = await asyncio.to_thread(self._curated_seed_and_pending)
        resolved: dict[int, int] = {}
        for entry_id, title, year in pending:
            try:
                tmdb_id = await self.tmdb.search_movie(title, year)
            except Exception as exc:  # noqa: BLE001 - best-effort resolution
                log.info("curated resolve failed for %r: %s", title, exc)
                continue
            if tmdb_id:
                resolved[entry_id] = tmdb_id
        applied = await asyncio.to_thread(self._curated_apply, resolved)
        return {"curated_resolved": applied}

    async def _resolve_canon(self) -> dict[str, int]:
        """Seed the canon and resolve a budgeted slice of it to TMDB ids.

        Seeding is free and idempotent; resolution is the part that costs API
        calls, so it is capped per scan. Entries carrying an IMDb id are resolved
        exactly; the few without fall back to a title-and-year search, which is a
        guess and is treated as one — a miss is a counted attempt, not a verdict.
        """
        if self.tmdb is None:
            return {}
        from ..services import canon_entries

        seeded = await asyncio.to_thread(self._seed_canon)
        pending = await asyncio.to_thread(
            self._canon_pending, canon_entries.CANON_BUDGET_OVERRIDE or CANON_RESOLVE_BUDGET
        )
        if not pending:
            return {"canon_seeded": seeded, "canon_resolved": 0}

        await self._note(f"resolving {len(pending):,} canon titles")
        resolved: dict[int, int | None] = {}
        for entry_id, imdb_id, title, year in pending:
            try:
                found = (
                    await self.tmdb.find_by_imdb(imdb_id)
                    if imdb_id
                    else await self.tmdb.search_movie(title, year)
                )
            except Exception as exc:  # noqa: BLE001 - resolution is best-effort
                log.info("canon resolve failed for %r: %s", title, exc)
                continue
            resolved[entry_id] = found
        found_count, exhausted = await asyncio.to_thread(self._canon_apply, resolved)
        return {
            "canon_seeded": seeded,
            "canon_resolved": found_count,
            "canon_unresolvable": exhausted,
        }

    def _seed_canon(self) -> int:
        from ..services import canon_entries

        with self.factory() as session:
            return canon_entries.seed(session)

    def _canon_pending(self, limit: int) -> list[tuple[int, str | None, str, int | None]]:
        from ..services import canon_entries

        with self.factory() as session:
            return canon_entries.pending_resolution(session, limit)

    def _canon_apply(self, resolved: dict[int, int | None]) -> tuple[int, int]:
        from ..services import canon_entries

        with self.factory() as session:
            return canon_entries.apply_resolution(session, resolved)

    def _curated_seed_and_pending(self) -> list[tuple[int, str, int | None]]:
        from ..services import curated_lists

        with self.factory() as session:
            curated_lists.seed_defaults(session)
            return curated_lists.pending_resolution(session)

    def _curated_apply(self, resolved: dict[int, int]) -> int:
        from ..services import curated_lists

        with self.factory() as session:
            return curated_lists.apply_resolution(session, resolved)

    async def _phase_finalize(self) -> dict[str, int]:
        counts = await asyncio.to_thread(self._finalize_counts)
        # Recommendations are computed here, once, rather than on every page load.
        # Sixty anchor calls is a reasonable thing to do during a scan the owner is
        # already waiting on, and an unreasonable thing to make them wait for every
        # time they open the page. A failure leaves the previous list standing.
        try:
            built = await recommend_analysis.refresh(self.factory, self.settings)
            counts["recommendations"] = built["stored"]
            # Recorded separately so a thin list can be read off the scan rather
            # than guessed at: canon needs no API call, taste needs dozens.
            counts["recommendations_canon"] = built["canon"]
            counts["recommendations_taste"] = built["taste"]
        except Exception as exc:  # noqa: BLE001 - never fail a scan over suggestions
            log.info("recommendation refresh failed: %s", exc)
        return counts

    async def _phase_score(self) -> dict[str, int]:
        # Deterministic junk scoring over the Plex library. Data decides the score.
        scored = await asyncio.to_thread(self._score)
        return {"scored": scored}

    async def _phase_ai(self) -> dict[str, int]:
        """Advisory AI pass over the freshly scored removal queue. Never changes a
        deterministic verdict. Everything — the imports included — sits inside the
        guard: this phase must never be the reason a finished scan reports failure.

        Bounded by ``AI_BUDGET_SECONDS``. Notes are written for whatever was reviewed
        before the budget ran out, so a slow provider degrades the pass instead of
        stalling the scan or losing the work already done.
        """
        try:
            from ..ai import review as ai_review
            from ..ai.registry import ai_configured

            if not ai_configured(self.settings):
                # Not an error — no provider is a legitimate configuration. Say so in
                # the counts rather than reporting a silent zero.
                return {"ai_skipped": 1}
            # only_new: don't re-spend tokens on candidates that already carry a
            # note; the Junk screen's explicit button refreshes everything.
            result = await ai_review.run_review(
                self.factory,
                self.settings,
                limit=50,
                only_new=True,
                budget_seconds=AI_BUDGET_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - advisory only; never fails the scan
            log.warning("ai analysis failed, continuing without it: %s", exc)
            return {"ai_failed": 1}
        counts = {"ai_reviewed": int(result.get("reviewed", 0))}
        if result.get("budget_exhausted"):
            # Surfaced so "only 12 of 50 got notes" reads as a slow provider rather
            # than a mystery.
            counts["ai_timed_out"] = 1
        return counts

    def _score(self) -> int:
        from ..services import curated_lists
        from ..services.settings_store import effective_junk

        with self.factory() as session:
            thr = effective_junk(session, self.settings)
            cult = curated_lists.cult_ids(session)
        return junk.compute_and_store(self.factory, thr, cult_ids=cult)

    # ------------------------------------------------------------- sync persistence

    def _load_checkpoints(self, scan_run_id: int) -> dict[str, Any]:
        with self.factory() as session:
            run = session.get(ScanRun, scan_run_id)
            return dict(run.checkpoints) if run and run.checkpoints else {}

    def _save_phase(self, scan_run_id: int, phase: str, counts: dict[str, int]) -> None:
        with self.factory() as session:
            run = session.get(ScanRun, scan_run_id)
            if run is None:
                return
            checkpoints = dict(run.checkpoints or {})
            checkpoints[phase] = {
                "status": "done",
                "counts": counts,
                "at": datetime.now(UTC).isoformat(),
            }
            run.checkpoints = checkpoints
            session.commit()

    def _finish(
        self, scan_run_id: int, status: ScanStatus, stats: dict[str, int], error: str | None
    ) -> ScanRun:
        with self.factory() as session:
            run = session.get(ScanRun, scan_run_id)
            if run is None:
                raise ValueError(f"scan_run {scan_run_id} not found")
            run.status = status
            run.stats = stats
            run.error = error
            if status in (ScanStatus.COMPLETED, ScanStatus.FAILED):
                run.finished_at = datetime.now(UTC)
            session.commit()
            session.refresh(run)
            session.expunge(run)
            return run

    def _sync_movie_media(
        self,
        session: Session,
        wanted: dict[int, list[dict[str, Any]]],
        *,
        source: str,
        rating_keys: dict[int, str | None] | None = None,
    ) -> int:
        """Reconcile ``media_files`` for a set of movies, from one source.

        Preloaded and batched throughout for the reason ``_persist_plex`` explains:
        on a hosted database a per-file lookup is a network round trip, and a large
        library has more files than films.

        A file's identity is its path — two sources reporting the same path are
        describing one file. Where a source gives no path the owner and source
        alone identify it, which is enough because a pathless record can only ever
        come from a single item.
        """
        ids = list(wanted)
        existing: dict[tuple[int, str], MediaFile] = {}
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            rows = session.scalars(
                select(MediaFile).where(
                    MediaFile.movie_tmdb_id.in_(batch), MediaFile.source == source
                )
            )
            for row in rows:
                existing[(row.movie_tmdb_id or 0, row.path or "")] = row

        written = 0
        seen: set[tuple[int, str]] = set()
        for tmdb_id, records in wanted.items():
            for record in records:
                key = (tmdb_id, record.get("path") or "")
                if key in seen:
                    # The same path twice in one payload is one file described
                    # twice, not two files; counting it twice would inflate the
                    # very total this feature exists to measure.
                    continue
                seen.add(key)
                found = existing.get(key)
                if found is None:
                    row = MediaFile(movie_tmdb_id=tmdb_id, source=source)
                    session.add(row)
                    existing[key] = row
                else:
                    row = found
                for field_name, value in record.items():
                    setattr(row, field_name, value)
                row.movie_tmdb_id = tmdb_id
                if rating_keys is not None:
                    row.rating_key = rating_keys.get(tmdb_id)
                row.seen_at = utcnow()
                written += 1
        stale = [
            row.id for key, row in existing.items() if key not in seen and row.id is not None
        ]
        for start in range(0, len(stale), 500):
            session.execute(delete(MediaFile).where(MediaFile.id.in_(stale[start : start + 500])))
        return written

    def _persist_radarr(
        self, movies: list[dict[str, Any]], collections: list[dict[str, Any]]
    ) -> dict[str, int]:
        written = 0
        with self.factory() as session:
            # Preloaded, both of them. This loop ran two queries per film — a
            # `session.get` for the row and another for its ratings — which is free
            # on SQLite and 10,000 network round trips against hosted Postgres for
            # a 5,000-film library. It is the same shape 2607.15.1 fixed in the
            # Plex phase and it was still here in the Radarr one.
            wanted = sorted({d["tmdb_id"] for d in movies if d.get("tmdb_id")})
            known: dict[int, Movie] = {}
            ratings_by_movie: dict[int, dict[RatingSource, Rating]] = {}
            for start in range(0, len(wanted), 500):
                chunk = wanted[start : start + 500]
                for row in session.scalars(select(Movie).where(Movie.tmdb_id.in_(chunk))):
                    known[row.tmdb_id] = row
                for rating in session.scalars(select(Rating).where(Rating.movie_id.in_(chunk))):
                    ratings_by_movie.setdefault(rating.movie_id, {})[rating.source] = rating

            for data in movies:
                tmdb_id = data["tmdb_id"]
                if not tmdb_id:
                    continue
                movie = known.get(tmdb_id)
                if movie is None:
                    movie = Movie(tmdb_id=tmdb_id, title="")
                    session.add(movie)
                    known[tmdb_id] = movie
                movie.radarr_id = data["radarr_id"]
                movie.imdb_id = data["imdb_id"] or movie.imdb_id
                movie.title = data["title"] or movie.title
                # Radarr runs after Plex now — a missing Radarr year must not
                # clobber the year Plex already provided.
                movie.year = data["year"] if data["year"] is not None else movie.year
                movie.runtime = data["runtime"]
                movie.genres = data["genres"]
                movie.overview = data["overview"]
                movie.poster_url = data["poster_url"]
                movie.monitored = data["monitored"]
                movie.has_file = data["has_file"]
                movie.quality = data["quality"]
                movie.cutoff_unmet = data["cutoff_unmet"]
                movie.file_size = data["file_size"]
                movie.added_at = data["added_at"]
                self._sync_ratings(
                    session, tmdb_id, data["ratings"], ratings_by_movie.get(tmdb_id, {})
                )
                written += 1
            for coll in collections:
                self._upsert_collection(session, coll)
            # Radarr's file detail fills the gaps Plex left. Plex is the library
            # authority, so where it already reported a file for a title, Radarr's
            # view of the same file is not stored a second time — the two mount the
            # same library at different paths, so both would count as separate
            # files and double the disk this feature is trying to measure.
            candidates = {
                d["tmdb_id"]: [d["media_file"]]
                for d in movies
                if d.get("tmdb_id") and d.get("media_file")
            }
            covered = self._movies_with_plex_media(session, list(candidates))
            files = self._sync_movie_media(
                session,
                {k: v for k, v in candidates.items() if k not in covered},
                source="radarr",
            )
            session.commit()
        return {
            "radarr_movies": written,
            "collections": len(collections),
            "radarr_media_files": files,
        }

    def _movies_with_plex_media(self, session: Session, ids: list[int]) -> set[int]:
        """Which of these films Plex has already described a file for."""
        covered: set[int] = set()
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            covered.update(
                session.scalars(
                    select(MediaFile.movie_tmdb_id).where(
                        MediaFile.movie_tmdb_id.in_(batch), MediaFile.source == "plex"
                    )
                )
            )
        return covered

    def _sync_ratings(
        self,
        session: Session,
        movie_id: int,
        ratings: list[dict[str, Any]],
        existing: dict[RatingSource, Rating],
    ) -> None:
        """Upsert one film's ratings against rows the caller already loaded.

        ``existing`` is passed in rather than queried here: this runs once per film,
        so a query of its own is one round trip per film in the largest loop of the
        Radarr phase.
        """
        for entry in ratings:
            source = RatingSource(entry["source"])
            row = existing.get(source)
            if row is None:
                session.add(
                    Rating(
                        movie_id=movie_id,
                        source=source,
                        value=entry["value"],
                        votes=entry["votes"],
                    )
                )
            else:
                row.value = entry["value"]
                row.votes = entry["votes"]

    def _upsert_collection(self, session: Session, coll: dict[str, Any]) -> None:
        coll_id = coll["tmdb_collection_id"]
        if not coll_id:
            return
        row = session.get(Collection, coll_id)
        if row is None:
            row = Collection(tmdb_collection_id=coll_id, name=coll["name"])
            session.add(row)
        else:
            row.name = coll["name"] or row.name
        existing = {
            m.tmdb_id: m
            for m in session.scalars(
                select(CollectionMember).where(CollectionMember.collection_id == coll_id)
            )
        }
        for member in coll["members"]:
            mid = member["tmdb_id"]
            if not mid:
                continue
            mrow = existing.get(mid)
            if mrow is None:
                session.add(
                    CollectionMember(
                        collection_id=coll_id,
                        tmdb_id=mid,
                        title=member["title"],
                        year=member["year"],
                        owned=member["owned"],
                    )
                )
            else:
                mrow.title = member["title"] or mrow.title
                mrow.year = member["year"]
                mrow.owned = member["owned"]

    def _persist_plex(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """Persist the Plex catalog.

        Everything here is preloaded in a handful of queries rather than looked up
        per film. On a hosted database every statement is a network round trip, so
        a per-item ``get`` plus a per-item ``merge`` over a few thousand films is
        tens of thousands of round trips — minutes of pure latency, which looks
        exactly like the phase having hung.
        """
        written = 0
        seen_keys: set[str] = set()
        with self.factory() as session:
            wanted = {d["tmdb_id"] for d in items if d.get("tmdb_id")}
            movies: dict[int, Movie] = {}
            # Chunked: a single IN() over a whole library can exceed the driver's
            # bind-parameter ceiling.
            ids = list(wanted)
            for start in range(0, len(ids), 500):
                batch = ids[start : start + 500]
                for m in session.scalars(select(Movie).where(Movie.tmdb_id.in_(batch))):
                    movies[m.tmdb_id] = m
            copies: dict[str, PlexCopy] = {
                c.rating_key: c for c in session.scalars(select(PlexCopy))
            }

            for data in items:
                tmdb_id = data["tmdb_id"]
                if not tmdb_id:
                    continue
                movie = movies.get(tmdb_id)
                if movie is None:
                    # In Plex but not in the Radarr catalog — Plex is the library
                    # authority, so this is a first-class library entry, not a stub.
                    movie = Movie(
                        tmdb_id=tmdb_id,
                        title=data["title"],
                        year=data["year"],
                    )
                    session.add(movie)
                    movies[tmdb_id] = movie
                # Presence in a Plex movie section IS library membership.
                movie.in_plex = True
                movie.plex_rating_key = data["plex_rating_key"]
                movie.library_section = data["library_section"]
                movie.is_kids = data["is_kids"]
                movie.title = movie.title or data["title"]
                movie.year = movie.year if movie.year is not None else data["year"]
                movie.imdb_id = movie.imdb_id or data["imdb_id"]
                # Record the *item*, not just the film. Without this a library
                # holding several rips of one title kept only the last rating key,
                # so duplicates were invisible and watch history reported against
                # the other copies was silently dropped.
                rating_key = data["plex_rating_key"]
                if rating_key:
                    key = str(rating_key)
                    copy = copies.get(key)
                    if copy is None:
                        # session.add, not session.merge: merge issues its own
                        # SELECT per call and flushes pending work each time,
                        # which is what made this phase crawl.
                        copy = PlexCopy(rating_key=key, movie_tmdb_id=tmdb_id)
                        session.add(copy)
                        copies[key] = copy
                    copy.movie_tmdb_id = tmdb_id
                    copy.library_section = data["library_section"]
                    copy.is_kids = bool(data["is_kids"])
                    copy.title = data["title"]
                    copy.seen_at = utcnow()
                    seen_keys.add(key)
                written += 1
            # Copies Plex no longer reports are gone from disk; drop them so a
            # tidied-up duplicate stops being counted as one. Computed against the
            # already-loaded map and issued as one statement per batch.
            if seen_keys:
                stale = [k for k in copies if k not in seen_keys]
                for start in range(0, len(stale), 500):
                    session.execute(
                        delete(PlexCopy).where(
                            PlexCopy.rating_key.in_(stale[start : start + 500])
                        )
                    )
            # Every file behind every copy, so a title held twice reports the disk
            # both rips actually occupy.
            by_movie: dict[int, list[dict[str, Any]]] = {}
            keys: dict[int, str | None] = {}
            for data in items:
                tmdb_id = data.get("tmdb_id")
                if not tmdb_id or not data.get("media_files"):
                    continue
                by_movie.setdefault(tmdb_id, []).extend(data["media_files"])
                keys.setdefault(tmdb_id, data.get("plex_rating_key"))
            files = self._sync_movie_media(
                session, by_movie, source="plex", rating_keys=keys
            )
            # Plex is the library authority: once it describes a title's files, a
            # stale Radarr row for the same title would be counted alongside them.
            superseded = [k for k in by_movie]
            for start in range(0, len(superseded), 500):
                session.execute(
                    delete(MediaFile).where(
                        MediaFile.movie_tmdb_id.in_(superseded[start : start + 500]),
                        MediaFile.source != "plex",
                    )
                )
            session.commit()
        return {"plex_items": written, "plex_media_files": files}

    def _persist_watch(self, aggregates: list[dict[str, Any]]) -> dict[str, int]:
        written = 0
        with self.factory() as session:
            # Map Plex ratingKey -> tmdb_id across EVERY copy, not just the one
            # that happened to land on the movie row. A duplicated title has several
            # rating keys, and Tautulli reports plays against whichever copy was
            # actually watched — matching only the primary silently discarded those
            # plays, which then read as "never played" and counted toward removal.
            rk_to_tmdb = {
                rk: tmdb
                for rk, tmdb in session.execute(
                    select(PlexCopy.rating_key, PlexCopy.movie_tmdb_id)
                )
            }
            # Fall back to the movie row for databases scanned before copies were
            # recorded, so watch history still lands until the next full scan.
            for rk, tmdb in session.execute(
                select(Movie.plex_rating_key, Movie.tmdb_id).where(
                    Movie.plex_rating_key.is_not(None)
                )
            ):
                rk_to_tmdb.setdefault(rk, tmdb)
            # Existing rows read once, keyed the way the loop looks them up. The
            # per-aggregate SELECT this replaces ran once per (film × Plex user),
            # so a four-person household with two thousand watched titles issued
            # up to eight thousand sequential statements every scan — free here on
            # SQLite, and the dominant cost against Neon. `_persist_show_watch`
            # already preloads; this was the film half that was missed.
            existing: dict[tuple[int, str | None], WatchHistory] = {
                (row.movie_id, row.plex_user): row
                for row in session.scalars(select(WatchHistory))
            }
            for data in aggregates:
                tmdb_id = rk_to_tmdb.get(data["plex_rating_key"])
                if tmdb_id is None:
                    continue
                key = (tmdb_id, data["plex_user"])
                row = existing.get(key)
                if row is None:
                    row = WatchHistory(movie_id=tmdb_id, plex_user=data["plex_user"])
                    session.add(row)
                    existing[key] = row
                row.plays = data["plays"]
                row.last_played_at = data["last_played_at"]
                row.completion_pct = data["completion_pct"]
                row.is_kids_account = data["is_kids_account"]
                written += 1
            session.commit()
        return {"watch_records": written}

    def _tmdb_targets(self, limit: int) -> list[int]:
        with self.factory() as session:
            rows = session.scalars(
                select(Movie.tmdb_id).where(Movie.in_plex.is_(True)).limit(limit)
            )
            return list(rows)

    def _persist_tmdb(self, enriched: list[dict[str, Any]]) -> dict[str, int]:
        written = 0
        with self.factory() as session:
            for data in enriched:
                tmdb_id = data["tmdb_id"]
                movie = session.get(Movie, tmdb_id) if tmdb_id else None
                if movie is None:
                    continue
                if data["keywords"]:
                    movie.keywords = data["keywords"]
                # Classifier facts (best-effort; absent → classifier stays neutral).
                if data.get("original_language"):
                    movie.original_language = data["original_language"]
                if data.get("budget") is not None:
                    movie.budget = data["budget"]
                movie.is_adult = bool(data.get("is_adult"))
                movie.us_theatrical = bool(data.get("us_theatrical"))
                movie.is_independent = bool(data.get("is_independent"))
                for person in data["people"]:
                    self._upsert_person(session, tmdb_id, person)
                if data["collection"]:
                    self._upsert_collection(
                        session, {**data["collection"], "members": []}
                    )
                written += 1
            session.commit()
        return {"tmdb_enriched": written}

    def _upsert_person(self, session: Session, movie_id: int, person: dict[str, Any]) -> None:
        prow = session.get(Person, person["id"])
        if prow is None:
            session.add(Person(id=person["id"], name=person["name"]))
        existing = session.scalars(
            select(MoviePerson).where(
                MoviePerson.movie_id == movie_id,
                MoviePerson.person_id == person["id"],
                MoviePerson.job == person["job"],
            )
        ).first()
        if existing is None:
            session.add(
                MoviePerson(movie_id=movie_id, person_id=person["id"], job=person["job"])
            )

    def _finalize_counts(self) -> dict[str, int]:
        with self.factory() as session:
            # "Owned" = in your Plex library (Plex is the source of truth).
            owned_ids = {
                tmdb
                for (tmdb,) in session.execute(
                    select(Movie.tmdb_id).where(Movie.in_plex.is_(True))
                )
            }
            # Grouped from one read. A query per collection is a round trip per
            # collection, which is the shape 2607.15.1 was about and is still worth
            # avoiding in a phase that runs on every scan.
            by_collection: dict[int, list[CollectionMember]] = {}
            for member in session.scalars(select(CollectionMember)):
                by_collection.setdefault(member.collection_id, []).append(member)

            for coll in session.scalars(select(Collection)):
                members = by_collection.get(coll.tmdb_collection_id, [])
                for m in members:
                    m.owned = m.tmdb_id in owned_ids
                coll.owned_count = sum(1 for m in members if m.owned)
                coll.total_count = len(members)
            total_movies = len(list(session.scalars(select(Movie.tmdb_id))))
            session.commit()
        return {"total_movies": total_movies, "in_plex": len(owned_ids)}
