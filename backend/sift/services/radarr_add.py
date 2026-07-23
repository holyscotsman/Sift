"""Build a complete Radarr 'add movie' request.

Radarr needs more than a TMDB id to add a title — a quality profile and a root
folder. The UI only knows the tmdb id, so we resolve sensible defaults from the
user's Radarr (first root folder + first quality profile) server-side. In dry-run
(staged) mode we don't need them; the payload is only logged.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..clients.radarr import RadarrClient
from ..config import RadarrConfig


def build_add_payload(
    tmdb_id: int,
    title: str,
    *,
    root_folder_path: str,
    quality_profile_id: int,
    monitored: bool = True,
    search: bool = True,
) -> dict[str, Any]:
    return {
        "tmdbId": tmdb_id,
        "title": title,
        "qualityProfileId": quality_profile_id,
        "rootFolderPath": root_folder_path,
        "monitored": monitored,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": search},
    }


async def resolve_add_options(
    config: RadarrConfig, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str | None, int | None]:
    """Return (root_folder_path, quality_profile_id).

    The owner's saved defaults win while Radarr still reports them; a stale saved
    value (folder removed, profile deleted) silently falls back to the first of
    each, so an add never fails because Settings drifted from Radarr."""
    if not config.base_url:
        return None, None
    client = RadarrClient(config, transport=transport)
    try:
        folders = await client.get_root_folders()
        profiles = await client.get_quality_profiles()
    finally:
        await client.aclose()
    paths = [f.get("path") for f in folders if f.get("path")]
    ids = [int(p["id"]) for p in profiles if p.get("id") is not None]
    root = (
        config.default_root_folder
        if config.default_root_folder in paths
        else (paths[0] if paths else None)
    )
    profile = (
        config.default_quality_profile_id
        if config.default_quality_profile_id in ids
        else (ids[0] if ids else None)
    )
    return root, profile
