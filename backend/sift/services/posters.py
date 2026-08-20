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

import asyncio
import logging
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..clients.tmdb import TmdbClient
from ..config import Settings
from ..db.models import CanonMovie, Movie
from ..db.session import in_thread

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
        self._client: httpx.AsyncClient | None = None
        base = settings.posters.cache_dir or (settings.database.path.parent / "cache")
        self._dir = Path(base) / "posters"
        # Running total of the cache directory, so the common write does not have
        # to stat every file on disk to find out whether it is over cap. None
        # means "unknown" — the next write measures once and then keeps count.
        self._bytes_on_disk: int | None = None

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
        self._bytes_on_disk = 0
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

    async def _stored_url(self, tmdb_id: int) -> str | None:
        """A poster URL we already hold, from either table that can hold one.

        The Missing page is entirely titles you do *not* own, so none of them has
        a ``movies`` row and every thumbnail fell through to a live TMDB lookup —
        one network round trip per poster, on a page that shows thirty at once.
        The path was already in the database the whole time: the canon refresh
        stores ``canon_movies.poster_path`` for exactly these titles. Nothing was
        reading it.

        It cannot be cached back into ``movies`` either, for the same reason —
        there is no row to write it to — so without this the lookup repeated
        every time the image cache went cold, which on an ephemeral disk is every
        redeploy.
        """

        def _read(session: Session) -> str | None:
            movie = session.get(Movie, tmdb_id)
            if movie is not None and movie.poster_url:
                return movie.poster_url
            path = session.scalar(
                select(CanonMovie.poster_path).where(CanonMovie.tmdb_id == tmdb_id)
            )
            if path:
                if path.startswith(("http://", "https://")):
                    return path
                return f"{_TMDB_IMG_BASE}{path}"
            return movie.poster_url if movie else None

        return await in_thread(self._factory, _read)

    async def _tmdb_url(self, tmdb_id: int, *, heal: bool = False) -> str | None:
        """Resolve artwork from TMDB by id and persist it. ``heal=True`` also
        overwrites a stored-but-broken URL (dead remoteUrl, old relative path)."""
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
        def _write(session: Session) -> None:
            movie = session.get(Movie, tmdb_id)
            if movie is not None and (heal or not movie.poster_url):
                movie.poster_url = url
                session.commit()

        await in_thread(self._factory, _write)
        return url

    async def _resolve_url(self, tmdb_id: int) -> str | None:
        stored = await self._stored_url(tmdb_id)
        # Stored relative paths (old scans stored Radarr's /MediaCover/…) are
        # unfetchable — ignore them so the TMDB fallback gets its chance.
        if stored and stored.startswith(("http://", "https://")):
            return stored
        return await self._tmdb_url(tmdb_id, heal=bool(stored))

    def _http(self) -> httpx.AsyncClient:
        """One client for the life of the cache, not one per poster.

        A client owns a connection pool, so building a new one per download meant
        a fresh TLS handshake to the image host every time — thirty of them when a
        page of thumbnails loads, where a shared pool needs a handful and reuses
        them. Created lazily so a cache that never fetches anything never opens a
        socket.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, transport=self._transport
            )
        return self._client

    async def aclose(self) -> None:
        """Release the pooled connections. Called when the app or a rebuilt
        service swaps this cache out."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def _download(self, url: str) -> bytes | None:
        try:
            resp = await self._http().get(url)
            resp.raise_for_status()
            return resp.content or None
        except Exception as exc:  # noqa: BLE001 - network hiccup → placeholder
            log.info("poster fetch failed from %s: %s", url, exc)
            return None

    async def get(self, tmdb_id: int) -> Path | None:
        """Return a path to the cached poster bytes, fetching + caching if needed."""
        hit = self.cached(tmdb_id)
        if hit is not None:
            return hit
        url = await self._resolve_url(tmdb_id)
        if not url:
            return None
        content = await self._download(url)
        if content is None and not url.startswith(_TMDB_IMG_BASE):
            # The stored URL is dead (stale remoteUrl, moved host). Re-resolve via
            # TMDB and heal the stored value so the next request skips the corpse.
            retry_url = await self._tmdb_url(tmdb_id, heal=True)
            if retry_url and retry_url != url:
                content = await self._download(retry_url)
        if content is None:
            return None
        path = self.path_for(tmdb_id)

        def _store() -> None:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            self._evict_over_cap(just_written=path)

        await asyncio.to_thread(_store)
        return path

    def _evict_over_cap(self, *, just_written: Path) -> None:
        """Oldest-first eviction once the cache exceeds the cap. The file just
        written is never a candidate — evicting it would defeat the fetch.

        The cap is nowhere near reached in ordinary use, so the check that
        decides "do I need to evict?" runs on every single poster fetch while
        the eviction itself almost never does. Statting the whole directory to
        answer it meant a library of fifteen thousand cached posters paid
        fifteen thousand syscalls per newly-fetched thumbnail — and a first
        scroll through the library fetches hundreds. Keep a running total
        instead and measure the directory only once per process, or after an
        eviction has actually changed it.
        """
        try:
            if self._bytes_on_disk is None:
                # First write of this process: one full measurement, which
                # already includes the file just written.
                self._bytes_on_disk = sum(f.stat().st_size for f in self._dir.glob("*.img"))
            else:
                self._bytes_on_disk += just_written.stat().st_size
            if self._bytes_on_disk <= _MAX_CACHE_BYTES:
                return
            others = [f for f in self._dir.glob("*.img") if f != just_written]
            total = sum(f.stat().st_size for f in others) + just_written.stat().st_size
            others.sort(key=lambda f: f.stat().st_mtime)
            for f in others:
                if total <= _MAX_CACHE_BYTES:
                    break
                size = f.stat().st_size
                f.unlink()
                total -= size
            self._bytes_on_disk = total
        except OSError as exc:
            # The count is only trustworthy while nothing surprising happened to
            # the directory; forget it and re-measure next time.
            self._bytes_on_disk = None
            log.debug("poster cache eviction hiccup: %s", exc)
