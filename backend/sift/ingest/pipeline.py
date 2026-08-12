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

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import junk
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

# Ceiling on the advisory AI pass. It's the last phase and reviews candidates one at
# a time, so without a bound a slow provider parks a finished scan on "AI analysis"
# for minutes. Whatever is done by then is kept.
AI_BUDGET_SECONDS = 120.0


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
        episodes: list[dict[str, Any]] = []
        for section in sections:
            kind = section.get("type")
            title = section.get("title", "")
            is_kids = title.lower() in kids
            if kind == "movie":
                raw_items = await self.plex.get_section_items(section["key"])
                for raw in raw_items:
                    items.append(
                        normalize.normalize_plex_item(raw, section_title=title, is_kids=is_kids)
                    )
            elif kind == "show":
                # Two passes over the section. Shows carry the TVDB guid that keys
                # them to Sonarr; episodes carry the files. Episodes are read flat
                # across the section rather than walked per series, which is a
                # request per page instead of one per show.
                for raw in await self.plex.get_section_items(section["key"], item_type=PLEX_SHOW):
                    show = normalize.normalize_plex_show(
                        raw, section_title=title, is_kids=is_kids
                    )
                    if show is not None:
                        shows.append(show)
                for raw in await self.plex.get_section_items(
                    section["key"], item_type=PLEX_EPISODE
                ):
                    episode = normalize.normalize_plex_episode(raw)
                    if episode is not None:
                        episodes.append(episode)
        counts = await asyncio.to_thread(self._persist_plex, items)
        if shows or episodes:
            counts.update(await asyncio.to_thread(self._persist_plex_tv, shows, episodes))
        return counts

    def _persist_plex_tv(
        self, shows: list[dict[str, Any]], episodes: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Record what Plex holds for TV, and every file behind it.

        Sonarr describes one file per episode, which is the right answer to "what
        should be there" and the wrong one for "what is actually on disk". Plex
        reports every copy it can see, so this is what makes a duplicated episode
        visible at all — the same reason ``plex_copies`` exists for films.
        """
        with self.factory() as session:
            existing: dict[int, Show] = {s.tvdb_id: s for s in session.scalars(select(Show))}
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
            session.flush()

            seasons: dict[tuple[int, int], Season] = {
                (s.show_id, s.season_number): s for s in session.scalars(select(Season))
            }
            known: dict[tuple[int, int], Episode] = {}
            for episode_row in session.scalars(select(Episode)):
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
        return {
            "plex_shows": len(shows),
            "plex_episodes": written,
            "plex_episode_files": files,
        }

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
        raw_series = await self.sonarr.get_series()
        series = [
            s for s in (normalize.normalize_sonarr_series(r) for r in raw_series) if s is not None
        ]
        detail: dict[int, dict[str, Any]] = {}
        for show in series:
            sonarr_id = show["sonarr_id"]
            if not sonarr_id:
                continue
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
        return await asyncio.to_thread(self._persist_sonarr, series, detail)

    def _persist_sonarr(
        self, series: list[dict[str, Any]], detail: dict[int, dict[str, Any]]
    ) -> dict[str, int]:
        """Persist shows, seasons, episodes and their files.

        Preloaded and batched throughout: a TV library has an order of magnitude
        more episodes than a film library has films, so the per-row lookups that
        merely slowed the Plex phase would be far worse here.
        """
        with self.factory() as session:
            tvdb_ids = [s["tvdb_id"] for s in series]
            shows: dict[int, Show] = {}
            for start in range(0, len(tvdb_ids), 500):
                batch = tvdb_ids[start : start + 500]
                for show_row in session.scalars(select(Show).where(Show.tvdb_id.in_(batch))):
                    shows[show_row.tvdb_id] = show_row
            seasons: dict[tuple[int, int], Season] = {
                (s.show_id, s.season_number): s for s in session.scalars(select(Season))
            }
            episodes: dict[tuple[int, int], Episode] = {}
            for episode_row in session.scalars(select(Episode)):
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
                by_number = {e["episode_number"]: e for e in found.get("episodes", [])}
                files_by_id = {
                    f["sonarr_episode_file_id"]: f for f in found.get("files", [])
                }
                # Air year is taken per season from the episodes themselves. The
                # series payload carries only one year, and a show's first year is
                # the wrong ceiling for its later seasons — Scrubs began in 2001
                # and ended in HD.
                years: dict[int, list[int]] = {}
                for episode in found.get("episodes", []):
                    if episode["air_date"]:
                        years.setdefault(episode["season_number"], []).append(
                            episode["air_date"].year
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

                    for episode_data in found.get("episodes", []):
                        if episode_data["season_number"] != number:
                            continue
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
                _ = by_number
            session.flush()
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
    ) -> int:
        """Reconcile ``media_files`` for episodes, from one source.

        Identity is the **path**, not the episode. A single "S01E01-E02" file is
        one file on disk that two episodes both point at, so keying on the episode
        would store it twice and report double the space it occupies. It is
        recorded once, against the first episode it covers.
        """

        def identity(path: str | None, episode_id: int | None) -> str:
            return path or f"episode:{episode_id}"

        existing: dict[str, MediaFile] = {}
        for row in session.scalars(
            select(MediaFile).where(MediaFile.episode_id.is_not(None), MediaFile.source == source)
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

        stale = [row.id for key, row in existing.items() if key not in seen and row.id is not None]
        for start in range(0, len(stale), 500):
            session.execute(delete(MediaFile).where(MediaFile.id.in_(stale[start : start + 500])))
        return written

    async def _phase_tautulli(self) -> dict[str, int]:
        if self.tautulli is None:
            return {}
        kids_accounts = set(self.settings.tautulli.kids_accounts)
        rows = await self.tautulli.get_history()
        normalized = [
            normalize.normalize_tautulli_row(r, kids_accounts=kids_accounts) for r in rows
        ]
        aggregates = normalize.aggregate_watch_rows(normalized)
        return await asyncio.to_thread(self._persist_watch, list(aggregates.values()))

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
        return await asyncio.to_thread(self._finalize_counts)

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

        stale = [row.id for key, row in existing.items() if key not in seen and row.id is not None]
        for start in range(0, len(stale), 500):
            session.execute(delete(MediaFile).where(MediaFile.id.in_(stale[start : start + 500])))
        return written

    def _upsert_movie(self, session: Session, tmdb_id: int) -> Movie:
        movie = session.get(Movie, tmdb_id)
        if movie is None:
            movie = Movie(tmdb_id=tmdb_id, title="")
            session.add(movie)
        return movie

    def _persist_radarr(
        self, movies: list[dict[str, Any]], collections: list[dict[str, Any]]
    ) -> dict[str, int]:
        written = 0
        with self.factory() as session:
            for data in movies:
                tmdb_id = data["tmdb_id"]
                if not tmdb_id:
                    continue
                movie = self._upsert_movie(session, tmdb_id)
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
                self._sync_ratings(session, tmdb_id, data["ratings"])
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

    def _sync_ratings(self, session: Session, movie_id: int, ratings: list[dict[str, Any]]) -> None:
        existing = {
            r.source: r
            for r in session.scalars(select(Rating).where(Rating.movie_id == movie_id))
        }
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
            for data in aggregates:
                tmdb_id = rk_to_tmdb.get(data["plex_rating_key"])
                if tmdb_id is None:
                    continue
                row = session.scalars(
                    select(WatchHistory).where(
                        WatchHistory.movie_id == tmdb_id,
                        WatchHistory.plex_user == data["plex_user"],
                    )
                ).first()
                if row is None:
                    row = WatchHistory(movie_id=tmdb_id, plex_user=data["plex_user"])
                    session.add(row)
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
            for coll in session.scalars(select(Collection)):
                members = session.scalars(
                    select(CollectionMember).where(
                        CollectionMember.collection_id == coll.tmdb_collection_id
                    )
                ).all()
                for m in members:
                    m.owned = m.tmdb_id in owned_ids
                coll.owned_count = sum(1 for m in members if m.owned)
                coll.total_count = len(members)
            total_movies = len(list(session.scalars(select(Movie.tmdb_id))))
            session.commit()
        return {"total_movies": total_movies, "in_plex": len(owned_ids)}
