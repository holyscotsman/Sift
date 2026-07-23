"""Poster resolution + on-disk cache.

Thumbnails must load for **every** library title, including Plex-only movies that
were never matched in Radarr — since Plex is the source of truth, most titles are
exactly that, and they carry no Radarr ``remoteUrl``. So we resolve a poster from
the stored URL when we have one, otherwise from TMDB by ``tmdb_id``, then cache the
bytes on disk keyed by id. The cache is what makes re-scans fast and is what the
"reset (keep thumbnails)" option preserves.

Resolution order per id:
1. cached file on disk → serve it;
2. ``movie.poster_url`` already stored (Radarr/TMDB) → download + cache;
3. TMDB lookup by id → build the image URL, persist it, download + cache;
4. nothing → ``None`` (the UI falls back to its gradient placeholder).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import Movie

log = logging.getLogger("sift.posters")

# w342 is a good grid/thumbnail width — small enough to cache cheaply, sharp enough
# for retina posters.
_TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w342"

# The cache serves thumbnails, not archives: cap it so a huge library on a small
# disk can't fill the volume poster by poster. A constant until someone needs a knob.
_MAX_CACHE_BYTES = 500 * 1024 * 1024


class PosterCache:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._factory = session_factory
        self._transport = transport  # test seam for both TMDB + image fetches
        base = settings.posters.cache_dir or (settings.database.path.parent / "cache")
        self._dir = Path(base) / "posters"

    # ------------------------------------------------------------------ disk cache

    def path_for(self, tmdb_id: int) -> Path:
        return self._dir / f"{tmdb_id}.img"

    def cached(self, tmdb_id: int) -> Path | None:
        p = self.path_for(tmdb_id)
        return p if p.is_file() and p.stat().st_size > 0 else None

    def clear(self) -> int:
        """Wipe the whole cache. NOT called by the keep-thumbnails reset."""
        count = 0
        if self._dir.is_dir():
            for f in self._dir.glob("*.img"):
                f.unlink()
                count += 1
        return count

    def stats(self) -> tuple[int, int]:
        """(file count, total bytes) of the on-disk cache. Zero when absent."""
        count = size = 0
        if self._dir.is_dir():
            for f in self._dir.glob("*.img"):
                count += 1
                size += f.stat().st_size
        return count, size

    # -------------------------------------------------------------------- resolve

    def _stored_url(self, tmdb_id: int) -> str | None:
        with self._factory() as session:
            movie = session.get(Movie, tmdb_id)
            return movie.poster_url if movie else None

    async def _resolve_url(self, tmdb_id: int) -> str | None:
        stored = self._stored_url(tmdb_id)
        if stored:
            return stored
        if not self._settings.tmdb.enabled or self._settings.tmdb.api_key is None:
            return None
        client = TmdbClient(self._settings.tmdb, transport=self._transport)
        try:
            data = await client.get_movie(tmdb_id, append="")
        except Exception as exc:  # noqa: BLE001 - best effort; fall back to placeholder
            log.info("tmdb poster lookup failed for %s: %s", tmdb_id, exc)
            return None
        finally:
            await client.aclose()
        poster_path = data.get("poster_path") if isinstance(data, dict) else None
        if not poster_path:
            return None
        url = f"{_TMDB_IMG_BASE}{poster_path}"
        # Persist so we never look it up twice (and a later scan keeps it).
        with self._factory() as session:
            movie = session.get(Movie, tmdb_id)
            if movie is not None and not movie.poster_url:
                movie.poster_url = url
                session.commit()
        return url

    async def get(self, tmdb_id: int) -> Path | None:
        """Return a path to the cached poster bytes, fetching + caching if needed."""
        hit = self.cached(tmdb_id)
        if hit is not None:
            return hit
        url = await self._resolve_url(tmdb_id)
        if not url:
            return None
        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, transport=self._transport
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content = resp.content
        except Exception as exc:  # noqa: BLE001 - network hiccup → placeholder
            log.info("poster fetch failed for %s: %s", tmdb_id, exc)
            return None
        if not content:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(tmdb_id)
        path.write_bytes(content)
        self._evict_over_cap(just_written=path)
        return path

    def _evict_over_cap(self, *, just_written: Path) -> None:
        """Oldest-first eviction once the cache exceeds the cap. The file just
        written is never a candidate — evicting it would defeat the fetch."""
        try:
            others = [f for f in self._dir.glob("*.img") if f != just_written]
            total = sum(f.stat().st_size for f in others) + just_written.stat().st_size
            if total <= _MAX_CACHE_BYTES:
                return
            others.sort(key=lambda f: f.stat().st_mtime)
            for f in others:
                if total <= _MAX_CACHE_BYTES:
                    break
                size = f.stat().st_size
                f.unlink()
                total -= size
        except OSError as exc:
            log.debug("poster cache eviction hiccup: %s", exc)
