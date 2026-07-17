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

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..analysis import junk
from ..clients.plex import PlexClient
from ..clients.radarr import RadarrClient
from ..clients.tautulli import TautulliClient
from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import (
    Collection,
    CollectionMember,
    Movie,
    MoviePerson,
    Person,
    Rating,
    RatingSource,
    ScanRun,
    ScanStatus,
    WatchHistory,
)
from . import normalize

log = logging.getLogger("sift.ingest")

PHASES = ("plex", "radarr", "tautulli", "tmdb", "finalize", "score", "ai")


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
        tautulli: TautulliClient | None = None,
        tmdb: TmdbClient | None = None,
        progress_cb: ProgressCallback | None = None,
        tmdb_enrich_limit: int = 0,
    ) -> None:
        self.factory = session_factory
        self.settings = settings
        self.radarr = radarr
        self.plex = plex
        self.tautulli = tautulli
        self.tmdb = tmdb
        self.progress_cb = progress_cb
        self.tmdb_enrich_limit = tmdb_enrich_limit

    # ---------------------------------------------------------------- orchestration

    async def run(self, scan_run_id: int, *, resume: bool = False) -> ScanRun:
        checkpoints = await asyncio.to_thread(self._load_checkpoints, scan_run_id)
        stats: dict[str, int] = {}
        try:
            for index, phase in enumerate(PHASES):
                if resume and checkpoints.get(phase, {}).get("status") == "done":
                    await self._emit(scan_run_id, phase, index, "skipped", "already complete")
                    stats.update(checkpoints[phase].get("counts", {}))
                    continue
                await self._emit(scan_run_id, phase, index, "running")
                counts = await getattr(self, f"_phase_{phase}")()
                stats.update(counts)
                await asyncio.to_thread(self._save_phase, scan_run_id, phase, counts)
                await self._emit(scan_run_id, phase, index, "done", counts=counts)
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised
            log.warning("scan %s interrupted during a phase: %s", scan_run_id, exc)
            await asyncio.to_thread(
                self._finish, scan_run_id, ScanStatus.INTERRUPTED, stats, str(exc)
            )
            raise
        return await asyncio.to_thread(
            self._finish, scan_run_id, ScanStatus.COMPLETED, stats, None
        )

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
        for section in sections:
            if section.get("type") != "movie":
                continue
            title = section.get("title", "")
            is_kids = title.lower() in kids
            raw_items = await self.plex.get_section_items(section["key"])
            for raw in raw_items:
                items.append(
                    normalize.normalize_plex_item(raw, section_title=title, is_kids=is_kids)
                )
        return await asyncio.to_thread(self._persist_plex, items)

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
        """Advisory AI pass over the freshly scored removal queue. Skips silently when
        no provider is configured; never changes a deterministic verdict. Everything —
        the imports included — sits inside the guard: this phase must never be the
        reason a finished scan reports failure."""
        try:
            from ..ai import review as ai_review
            from ..ai.registry import ai_configured

            if not ai_configured(self.settings):
                return {}
            # only_new: don't re-spend tokens on candidates that already carry a
            # note; the Junk screen's explicit button refreshes everything.
            result = await ai_review.run_review(
                self.factory, self.settings, limit=50, only_new=True
            )
        except Exception as exc:  # noqa: BLE001 - advisory only; never fails the scan
            log.info("ai analysis skipped: %s", exc)
            return {}
        return {"ai_reviewed": int(result.get("reviewed", 0))}

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
            session.commit()
        return {"radarr_movies": written, "collections": len(collections)}

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
        written = 0
        with self.factory() as session:
            for data in items:
                tmdb_id = data["tmdb_id"]
                if not tmdb_id:
                    continue
                movie = session.get(Movie, tmdb_id)
                if movie is None:
                    # In Plex but not in the Radarr catalog — Plex is the library
                    # authority, so this is a first-class library entry, not a stub.
                    movie = Movie(
                        tmdb_id=tmdb_id,
                        title=data["title"],
                        year=data["year"],
                    )
                    session.add(movie)
                # Presence in a Plex movie section IS library membership.
                movie.in_plex = True
                movie.plex_rating_key = data["plex_rating_key"]
                movie.library_section = data["library_section"]
                movie.is_kids = data["is_kids"]
                movie.title = movie.title or data["title"]
                movie.year = movie.year if movie.year is not None else data["year"]
                movie.imdb_id = movie.imdb_id or data["imdb_id"]
                written += 1
            session.commit()
        return {"plex_items": written}

    def _persist_watch(self, aggregates: list[dict[str, Any]]) -> dict[str, int]:
        written = 0
        with self.factory() as session:
            # Map Plex ratingKey -> tmdb_id from the movies already ingested.
            rk_to_tmdb = {
                rk: tmdb
                for rk, tmdb in session.execute(
                    select(Movie.plex_rating_key, Movie.tmdb_id).where(
                        Movie.plex_rating_key.is_not(None)
                    )
                )
            }
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
