"""Poster thumbnails, resolved + cached server-side.

Served from ``/api/poster/{tmdb_id}`` so every library title has a thumbnail —
including Plex-only movies with no Radarr artwork. Because an ``<img>`` tag can't
send an auth header, this route also accepts the token as a ``?token=`` query
param (same pattern as the scan WebSocket); the header is honoured too.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import FileResponse

from .deps import get_state

router = APIRouter(prefix="/api", tags=["posters"])


def _authorize(
    request: Request,
    token: str | None,
    authorization: str | None,
    x_sift_token: str | None,
) -> None:
    configured = get_state(request).settings.server.api_token
    if configured is None:
        return
    secret = configured.get_secret_value()
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:]
    if secret in (token, x_sift_token, bearer):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")


@router.get("/poster/{tmdb_id}")
async def poster(
    tmdb_id: int,
    request: Request,
    token: str | None = None,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> FileResponse:
    _authorize(request, token, authorization, x_sift_token)
    path = await get_state(request).posters.get(tmdb_id)
    if path is None:
        # No artwork available — the UI falls back to its gradient placeholder.
        raise HTTPException(status_code=404, detail="no poster")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},  # a week; ids are stable
    )
