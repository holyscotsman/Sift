"""Canonical identity normalization.

Each source speaks its own dialect; these pure functions translate a raw record
into a canonical fragment keyed on ``tmdb_id``. Keeping them side-effect-free makes
them cheap to unit-test and to property-test the cross-source id resolver later.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

_TMDB_GUID = re.compile(r"tmdb://(\d+)")
_IMDB_GUID = re.compile(r"imdb://(tt\d+)")
_LEGACY_TMDB = re.compile(r"themoviedb://(\d+)")
_LEGACY_IMDB = re.compile(r"imdb://(tt\d+)|(tt\d+)")


def parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or unix timestamp into an aware UTC datetime."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=UTC)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n or None


# ------------------------------------------------------------------------ Radarr


def normalize_radarr_movie(raw: dict[str, Any]) -> dict[str, Any]:
    tmdb_id = _int_or_none(raw.get("tmdbId"))
    poster_url = None
    for image in raw.get("images", []) or []:
        if image.get("coverType") == "poster":
            poster_url = image.get("remoteUrl") or image.get("url")
            break

    quality = None
    movie_file = raw.get("movieFile") or {}
    quality = (((movie_file.get("quality") or {}).get("quality")) or {}).get("name")

    ratings: list[dict[str, Any]] = []
    for source, block in (raw.get("ratings") or {}).items():
        if source not in ("tmdb", "imdb"):
            continue
        if not isinstance(block, dict) or block.get("value") in (None, 0):
            continue
        ratings.append(
            {
                "source": source,
                "value": float(block["value"]),
                "votes": _int_or_none(block.get("votes")),
            }
        )

    collection = None
    raw_collection = raw.get("collection")
    if isinstance(raw_collection, dict):
        coll_id = _int_or_none(raw_collection.get("tmdbId"))
        if coll_id:
            collection = {"tmdb_collection_id": coll_id, "name": raw_collection.get("title", "")}

    return {
        "tmdb_id": tmdb_id,
        "radarr_id": _int_or_none(raw.get("id")),
        "imdb_id": raw.get("imdbId") or None,
        "title": raw.get("title") or "",
        "year": _int_or_none(raw.get("year")),
        "runtime": _int_or_none(raw.get("runtime")),
        "genres": list(raw.get("genres", []) or []),
        "overview": raw.get("overview") or None,
        "poster_url": poster_url,
        "monitored": bool(raw.get("monitored", False)),
        "has_file": bool(raw.get("hasFile", False)),
        "quality": quality,
        "file_size": _int_or_none(raw.get("sizeOnDisk")),
        "added_at": parse_dt(raw.get("added")),
        "ratings": ratings,
        "collection": collection,
    }


def normalize_radarr_collection(raw: dict[str, Any]) -> dict[str, Any]:
    members = []
    for m in raw.get("movies", []) or []:
        members.append(
            {
                "tmdb_id": _int_or_none(m.get("tmdbId")),
                "title": m.get("title", ""),
                "year": _int_or_none(m.get("year")),
                # Radarr marks a collection movie present in the library via monitored/added.
                "owned": bool(m.get("monitored")) or _int_or_none(m.get("id")) is not None,
            }
        )
    members = [m for m in members if m["tmdb_id"]]
    return {
        "tmdb_collection_id": _int_or_none(raw.get("tmdbId")),
        "name": raw.get("title", ""),
        "members": members,
    }


# -------------------------------------------------------------------------- Plex


def extract_plex_ids(item: dict[str, Any]) -> tuple[int | None, str | None]:
    """Pull (tmdb_id, imdb_id) from a Plex item's Guid list or legacy guid string."""
    tmdb_id: int | None = None
    imdb_id: str | None = None
    for guid in item.get("Guid", []) or []:
        gid = guid.get("id", "")
        if not tmdb_id and (m := _TMDB_GUID.search(gid)):
            tmdb_id = int(m.group(1))
        if not imdb_id and (m := _IMDB_GUID.search(gid)):
            imdb_id = m.group(1)
    legacy = item.get("guid", "") or ""
    if not tmdb_id and (m := _LEGACY_TMDB.search(legacy)):
        tmdb_id = int(m.group(1))
    if not imdb_id and (m := _IMDB_GUID.search(legacy)):
        imdb_id = m.group(1)
    return tmdb_id, imdb_id


def normalize_plex_item(
    item: dict[str, Any], *, section_title: str, is_kids: bool
) -> dict[str, Any]:
    tmdb_id, imdb_id = extract_plex_ids(item)
    return {
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "plex_rating_key": (
            str(item.get("ratingKey")) if item.get("ratingKey") is not None else None
        ),
        "title": item.get("title") or "",
        "year": _int_or_none(item.get("year")),
        "library_section": section_title,
        "is_kids": is_kids,
        "user_rating": item.get("userRating"),
    }


# ---------------------------------------------------------------------- Tautulli


def normalize_tautulli_row(row: dict[str, Any], *, kids_accounts: set[str]) -> dict[str, Any]:
    user = row.get("friendly_name") or row.get("user") or "unknown"
    percent = row.get("percent_complete")
    return {
        "plex_rating_key": (
            str(row.get("rating_key")) if row.get("rating_key") is not None else None
        ),
        "plex_user": user,
        "played_at": parse_dt(row.get("date")),
        "completion_pct": (float(percent) / 100.0) if percent not in (None, "") else None,
        "is_kids_account": user in kids_accounts,
    }


def aggregate_watch_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Collapse per-session history into per-(movie, user) aggregates."""
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key_val = row.get("plex_rating_key")
        if not key_val:
            continue
        key = (key_val, row["plex_user"])
        entry = agg.get(key)
        if entry is None:
            entry = {
                "plex_rating_key": key_val,
                "plex_user": row["plex_user"],
                "plays": 0,
                "last_played_at": None,
                "completion_pct": None,
                "is_kids_account": row["is_kids_account"],
                "_completions": [],
            }
            agg[key] = entry
        entry["plays"] += 1
        played = row.get("played_at")
        if played and (entry["last_played_at"] is None or played > entry["last_played_at"]):
            entry["last_played_at"] = played
        if row.get("completion_pct") is not None:
            entry["_completions"].append(row["completion_pct"])
    for entry in agg.values():
        comps = entry.pop("_completions")
        entry["completion_pct"] = round(sum(comps) / len(comps), 4) if comps else None
    return agg


# -------------------------------------------------------------------------- TMDB


def normalize_tmdb_movie(raw: dict[str, Any]) -> dict[str, Any]:
    keywords = [
        k.get("name")
        for k in ((raw.get("keywords") or {}).get("keywords") or [])
        if k.get("name")
    ]
    people: list[dict[str, Any]] = []
    credits = raw.get("credits") or {}
    for crew in credits.get("crew", []) or []:
        if crew.get("job") == "Director" and crew.get("id"):
            people.append({"id": int(crew["id"]), "name": crew.get("name", ""), "job": "director"})
    for cast in (credits.get("cast", []) or [])[:8]:
        if cast.get("id"):
            people.append({"id": int(cast["id"]), "name": cast.get("name", ""), "job": "actor"})

    collection = None
    belongs = raw.get("belongs_to_collection")
    if isinstance(belongs, dict) and belongs.get("id"):
        collection = {"tmdb_collection_id": int(belongs["id"]), "name": belongs.get("name", "")}

    return {
        "tmdb_id": _int_or_none(raw.get("id")),
        "keywords": keywords,
        "people": people,
        "collection": collection,
    }
