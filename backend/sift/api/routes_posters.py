"""Poster thumbnails, resolved + cached server-side.

Served from ``/api/poster/{tmdb_id}`` so every library title has a thumbnail —
including Plex-only movies with no Radarr artwork. Because an ``<img>`` tag can't
send an auth header, this route also accepts the token as a ``?token=`` query
param (same pattern as the scan WebSocket); the header is honoured too.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from .deps import AuthDep, get_state, presented_token, token_accepted
from .schemas import PosterCacheStats

router = APIRouter(prefix="/api", tags=["posters"])


@router.get("/posters/stats", response_model=PosterCacheStats, dependencies=[AuthDep])
def poster_stats(request: Request) -> PosterCacheStats:
    count, size = get_state(request).posters.stats()
    return PosterCacheStats(count=count, bytes=size)


@router.post("/posters/clear", response_model=PosterCacheStats, dependencies=[AuthDep])
def poster_clear(request: Request) -> PosterCacheStats:
    """Empty the thumbnail cache (never touches the DB); posters refill on demand."""
    cleared = get_state(request).posters.clear()
    return PosterCacheStats(count=cleared, bytes=0)


@router.get("/poster/{tmdb_id}")
async def poster(
    tmdb_id: int,
    request: Request,
    token: str | None = None,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> FileResponse:
    # <img> can't send headers, so the token also comes via ?token=.
    presented = token or presented_token(authorization, x_sift_token)
    if not token_accepted(get_state(request), presented):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    path = await get_state(request).posters.get(tmdb_id)
    if path is None:
        # No artwork available — the UI falls back to its gradient placeholder.
        raise HTTPException(status_code=404, detail="no poster")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},  # a week; ids are stable
    )
