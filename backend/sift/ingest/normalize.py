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


# -------------------------------------------------------------------- media info

# Rungs of the resolution ladder, as (exclusive minimum height, label). Judged on
# height rather than width so 1920x800 scope and 1920x1080 flat both read as
# 1080p — comparing widths files every letterboxed film one rung too high.
_RESOLUTION_RUNGS = ((1600, "2160p"), (1080, "1440p"), (720, "1080p"), (576, "720p"), (0, "480p"))

_HHMMSS = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$")


def resolution_label(height: Any, fallback: Any = None) -> str | None:
    """Normalise a pixel height onto the ladder.

    ``fallback`` takes a source's own label — Plex reports ``videoResolution`` as
    "sd"/"720"/"1080"/"4k" — for files that carry no usable height.
    """
    h = _int_or_none(height)
    if h:
        for floor, label in _RESOLUTION_RUNGS:
            if h > floor:
                return label
    text = str(fallback or "").strip().lower()
    if text in ("4k", "2160", "2160p", "uhd"):
        return "2160p"
    if text in ("1440", "1440p"):
        return "1440p"
    if text in ("1080", "1080p", "hd"):
        return "1080p"
    if text in ("720", "720p"):
        return "720p"
    if text in ("sd", "480", "480p", "576", "576p"):
        return "480p"
    return None


def parse_duration_ms(value: Any) -> int | None:
    """Milliseconds, from a raw number or Radarr's ``HH:MM:SS.fff`` runtime string."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)):
        return int(value) or None
    text = str(value).strip()
    if text.isdigit():
        return int(text) or None
    if m := _HHMMSS.match(text):
        hours, minutes, seconds, frac = m.groups()
        total = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
        if frac:
            total += int(frac[:3].ljust(3, "0"))
        return total or None
    return None


def _codec(value: Any) -> str | None:
    """Fold the many spellings of a codec onto one name.

    Sources disagree — ``x265``/``hevc``/``HEVC`` name one codec — and the bitrate
    baselines are computed per codec, so leaving the spellings distinct would split
    one population into three too-small ones and make every median untrustworthy.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in ("hevc", "h265", "h.265", "x265", "hev1", "hvc1"):
        return "h265"
    if text in ("avc", "h264", "h.264", "x264", "avc1"):
        return "h264"
    if text in ("av1", "av01"):
        return "av1"
    if text in ("mpeg2video", "mpeg2"):
        return "mpeg2"
    if text in ("vc1", "vc-1"):
        return "vc1"
    return text[:32]


def _dimensions(info: dict[str, Any]) -> tuple[int | None, int | None]:
    """Width/height from explicit fields or from a ``1920x1080`` resolution string."""
    width = _int_or_none(info.get("width"))
    height = _int_or_none(info.get("height"))
    if width and height:
        return width, height
    text = str(info.get("resolution") or "").lower()
    if "x" in text:
        left, _, right = text.partition("x")
        return _int_or_none(left) or width, _int_or_none(right) or height
    return width, height


def normalize_media_info(
    info: dict[str, Any] | None,
    *,
    path: Any = None,
    size: Any = None,
    container: Any = None,
    source: str,
) -> dict[str, Any] | None:
    """A canonical media-file fragment, or ``None`` when there is nothing to say.

    A record with neither a size nor a duration cannot take part in any bitrate
    calculation, so it is dropped rather than stored as a hole every later query
    would have to guard against.
    """
    info = info or {}
    width, height = _dimensions(info)
    size_bytes = _int_or_none(size)
    duration = parse_duration_ms(info.get("runTime") or info.get("duration"))
    if size_bytes is None and duration is None:
        return None
    return {
        "path": (str(path) if path else None),
        "container": (str(container).lstrip(".").lower() if container else None),
        "size": size_bytes,
        "duration_ms": duration,
        "width": width,
        "height": height,
        "resolution": resolution_label(height, info.get("videoResolution")),
        "video_codec": _codec(info.get("videoCodec")),
        "audio_codec": _codec(info.get("audioCodec")),
        "source": source,
    }


# ------------------------------------------------------------------------ Radarr


def normalize_radarr_movie(raw: dict[str, Any]) -> dict[str, Any]:
    tmdb_id = _int_or_none(raw.get("tmdbId"))
    poster_url = None
    for image in raw.get("images", []) or []:
        if image.get("coverType") == "poster":
            # Only an absolute URL is fetchable by the poster cache. Radarr's
            # ``url`` is a Radarr-relative path (/MediaCover/…) — storing it broke
            # thumbnails for titles without a remoteUrl; skip it and let the
            # cache's TMDB-by-id fallback resolve artwork instead.
            candidate = image.get("remoteUrl") or image.get("url")
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                poster_url = candidate
            break

    quality = None
    movie_file = raw.get("movieFile") or {}
    quality = (((movie_file.get("quality") or {}).get("quality")) or {}).get("name")

    has_file = bool(raw.get("hasFile", False))
    # Radarr surfaces "current quality is below the profile cutoff" as
    # qualityCutoffNotMet. Its exact location moved across versions (movieFile vs the
    # movie root), so read both. Only meaningful when a file actually exists.
    cutoff_unmet = has_file and bool(
        movie_file.get("qualityCutoffNotMet") or raw.get("qualityCutoffNotMet")
    )

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
        "has_file": has_file,
        "quality": quality,
        "cutoff_unmet": cutoff_unmet,
        "file_size": _int_or_none(raw.get("sizeOnDisk")),
        "added_at": parse_dt(raw.get("added")),
        "ratings": ratings,
        "collection": collection,
        # The technical detail was always in this payload; it was simply dropped
        # after ``quality`` was read out of the same dict.
        "media_file": normalize_media_info(
            movie_file.get("mediaInfo"),
            path=movie_file.get("path"),
            size=movie_file.get("size") or raw.get("sizeOnDisk"),
            container=(movie_file.get("path") or "").rpartition(".")[2] or None,
            source="radarr",
        )
        if has_file
        else None,
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
        "media_files": plex_media_files(item),
    }


def plex_media_files(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Every file backing one Plex item.

    A list, not a single record: Plex models an item's alternate versions as
    several ``Media`` entries, and a long episode split across discs as several
    ``Part`` entries under one ``Media``. Collapsing either to "the first one"
    would under-report the disk in use, which is the whole quantity being measured.
    """
    out: list[dict[str, Any]] = []
    for index, media in enumerate(item.get("Media", []) or []):
        if not isinstance(media, dict):
            continue
        # One Media is one presentation. Its Parts are that presentation split
        # across files, which is why they must never be mistaken for copies.
        group = str(media.get("id") or f"media{index}")
        for part in media.get("Part", []) or []:
            if not isinstance(part, dict):
                continue
            record = normalize_media_info(
                {
                    "width": media.get("width"),
                    "height": media.get("height"),
                    "videoResolution": media.get("videoResolution"),
                    "videoCodec": media.get("videoCodec"),
                    "audioCodec": media.get("audioCodec"),
                    # Part duration wins: a split file's own length is what the
                    # bitrate maths needs, not the whole item's.
                    "duration": part.get("duration") or media.get("duration"),
                },
                path=part.get("file"),
                size=part.get("size"),
                container=part.get("container") or media.get("container"),
                source="plex",
            )
            if record is not None:
                record["part_group"] = group
                out.append(record)
    return out


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


# Studios that mark a film as decidedly non-independent. Lower-cased substring match.
_MAJOR_STUDIOS = (
    "warner", "universal", "paramount", "walt disney", "disney", "columbia", "sony",
    "20th century", "twentieth century", "fox", "metro-goldwyn", "mgm", "lionsgate",
    "lions gate", "dreamworks", "new line", "miramax", "netflix", "amazon", "apple",
    "marvel", "lucasfilm", "pixar", "legendary", "blumhouse", "a24",
)
# Adult/porn keyword signals (TMDB's own ``adult`` flag is the primary tell).
_ADULT_KEYWORDS = ("pornographic", "hardcore", "softcore", "adult film", "erotica")


def _us_theatrical(raw: dict[str, Any]) -> bool:
    """Theatrical-SCALE release, not merely a theater booking.

    True when TMDB lists a US theatrical (type 2/3) release date, OR a major
    studio is attached, OR the budget is studio-scale (≥ $20M). The owner's
    rule: a big-studio film (Disney's Snow White, Amazon's War of the Worlds)
    is kept even when it scored badly — people watch those *because* they're
    bad. Junk stays aimed at low-budget/independent/non-theatrical fare."""
    for entry in ((raw.get("release_dates") or {}).get("results") or []):
        if entry.get("iso_3166_1") != "US":
            continue
        for rel in entry.get("release_dates", []) or []:
            if rel.get("type") in (2, 3):  # 2 = limited theatrical, 3 = theatrical
                return True
    companies = [str(c.get("name", "")).lower() for c in (raw.get("production_companies") or [])]
    if any(any(m in name for m in _MAJOR_STUDIOS) for name in companies):
        return True
    return (_int_or_none(raw.get("budget")) or 0) >= 20_000_000


def _is_independent(raw: dict[str, Any]) -> bool:
    """Heuristic: a real but small budget and no major studio attached. Conservative —
    an unknown budget is treated as *not* independent so we never force-remove blindly.
    """
    budget = _int_or_none(raw.get("budget")) or 0
    companies = [str(c.get("name", "")).lower() for c in (raw.get("production_companies") or [])]
    major = any(any(m in name for m in _MAJOR_STUDIOS) for name in companies)
    return 0 < budget < 5_000_000 and not major


def _is_adult(raw: dict[str, Any], keywords: list[str]) -> bool:
    if bool(raw.get("adult")):
        return True
    haystack = " ".join(keywords).lower()
    return any(term in haystack for term in _ADULT_KEYWORDS)


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
        "original_language": raw.get("original_language") or None,
        "budget": _int_or_none(raw.get("budget")),
        "is_adult": _is_adult(raw, keywords),
        "us_theatrical": _us_theatrical(raw),
        "is_independent": _is_independent(raw),
    }


# ---------------------------------------------------------------------- Sonarr

_TVDB_GUID = re.compile(r"tvdb://(\d+)")


def normalize_sonarr_series(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A series and its per-season statistics.

    Sonarr reports ``sizeOnDisk`` and episode counts per season on this one
    payload, so the "which show is heaviest" question is answered for the whole
    library without touching a single episode.
    """
    tvdb_id = _int_or_none(raw.get("tvdbId"))
    if not tvdb_id:
        # Without the id there is nothing to key on and nothing Plex can be
        # matched against, so the row would be unreachable rather than merely
        # incomplete.
        return None
    seasons = []
    for season in raw.get("seasons", []) or []:
        if not isinstance(season, dict):
            continue
        number = season.get("seasonNumber")
        if number is None:
            continue
        stats = season.get("statistics") or {}
        seasons.append(
            {
                "season_number": int(number),
                "size_on_disk": _int_or_none(stats.get("sizeOnDisk")),
                "episode_count": int(
                    stats.get("totalEpisodeCount") or stats.get("episodeCount") or 0
                ),
                "episode_file_count": int(stats.get("episodeFileCount") or 0),
            }
        )
    return {
        "tvdb_id": tvdb_id,
        "tmdb_id": _int_or_none(raw.get("tmdbId")),
        "sonarr_id": _int_or_none(raw.get("id")),
        "title": raw.get("title") or "",
        "year": _int_or_none(raw.get("year")),
        "status": raw.get("status") or None,
        "network": raw.get("network") or None,
        "genres": list(raw.get("genres", []) or []),
        # Sonarr's runtime is the typical episode length, which is exactly the
        # signal wanted: a 22-minute comedy and a 55-minute drama ask different
        # things of the picture.
        "runtime": _int_or_none(raw.get("runtime")),
        "monitored": bool(raw.get("monitored", False)),
        "quality_profile_id": _int_or_none(raw.get("qualityProfileId")),
        "original_language": (raw.get("originalLanguage") or {}).get("name")
        if isinstance(raw.get("originalLanguage"), dict)
        else None,
        "seasons": seasons,
    }


def normalize_sonarr_episode(raw: dict[str, Any]) -> dict[str, Any] | None:
    season = raw.get("seasonNumber")
    number = raw.get("episodeNumber")
    if season is None or number is None:
        return None
    return {
        "season_number": int(season),
        "episode_number": int(number),
        "title": raw.get("title") or None,
        "air_date": parse_dt(raw.get("airDateUtc") or raw.get("airDate")),
        "sonarr_episode_id": _int_or_none(raw.get("id")),
        # The exact discriminator for multi-episode files: two episodes sharing a
        # file id are one file, not a duplicate.
        "sonarr_episode_file_id": _int_or_none(raw.get("episodeFileId")),
        "has_file": bool(raw.get("hasFile", False)),
    }


def normalize_sonarr_episode_file(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One episode file, as a media-file fragment tagged with its Sonarr id."""
    file_id = _int_or_none(raw.get("id"))
    if not file_id:
        return None
    record = normalize_media_info(
        raw.get("mediaInfo"),
        path=raw.get("path"),
        size=raw.get("size"),
        container=(raw.get("path") or "").rpartition(".")[2] or None,
        source="sonarr",
    )
    if record is None:
        return None
    record["sonarr_episode_file_id"] = file_id
    # Sonarr reports one file per presentation, so each is its own group.
    record["part_group"] = str(file_id)
    return record


# ------------------------------------------------------------------- Plex (TV)


def normalize_plex_show(
    item: dict[str, Any], *, section_title: str, is_kids: bool
) -> dict[str, Any] | None:
    """A show, keyed on the TVDB id Sonarr also speaks."""
    tvdb_id = None
    for guid in item.get("Guid", []) or []:
        value = guid.get("id", "") if isinstance(guid, dict) else ""
        if m := _TVDB_GUID.search(value):
            tvdb_id = int(m.group(1))
            break
    if tvdb_id is None and (m := _TVDB_GUID.search(item.get("guid", "") or "")):
        tvdb_id = int(m.group(1))
    if tvdb_id is None:
        return None
    tmdb_id, _imdb = extract_plex_ids(item)
    return {
        "tvdb_id": tvdb_id,
        "tmdb_id": tmdb_id,
        "plex_rating_key": (
            str(item.get("ratingKey")) if item.get("ratingKey") is not None else None
        ),
        "title": item.get("title") or "",
        "year": _int_or_none(item.get("year")),
        "library_section": section_title,
        "is_kids": is_kids,
    }


def normalize_plex_episode(item: dict[str, Any]) -> dict[str, Any] | None:
    """One episode, tied back to its show by Plex's grandparent rating key.

    ``parentIndex``/``index`` are the season and episode numbers. An episode
    missing either cannot be placed in a season, and a duplicate detector that
    guessed their position would group unrelated files together.
    """
    season = item.get("parentIndex")
    number = item.get("index")
    show_key = item.get("grandparentRatingKey")
    if season is None or number is None or show_key is None:
        return None
    return {
        "show_rating_key": str(show_key),
        "season_number": int(season),
        "episode_number": int(number),
        "title": item.get("title") or None,
        "plex_rating_key": (
            str(item.get("ratingKey")) if item.get("ratingKey") is not None else None
        ),
        "media_files": plex_media_files(item),
    }


def normalize_tautulli_episode_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """One episode play, tied to its show by Plex's grandparent rating key.

    Keeps two fields the movie normalizer drops. ``video_resolution`` is what was
    actually delivered to a player, which is a far better answer to "does this
    show need to be in HD" than anything about the file — a show only ever
    watched at 720p on a phone is not being asked for 4K.
    """
    show_key = row.get("grandparent_rating_key")
    if show_key in (None, "", 0, "0"):
        return None
    percent = row.get("percent_complete")
    return {
        "show_rating_key": str(show_key),
        "played_at": parse_dt(row.get("date")),
        "completion_pct": (float(percent) / 100.0) if percent not in (None, "") else None,
        "stream_height": _stream_height(row.get("video_resolution")),
    }


def _stream_height(value: Any) -> int | None:
    """Pixel height from Tautulli's delivered-resolution label."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in ("4k", "uhd", "2160", "2160p"):
        return 2160
    digits = "".join(c for c in text if c.isdigit())
    if digits:
        return int(digits)
    if text == "sd":
        return 480
    return None


def aggregate_show_watch(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse episode plays into one record per show."""
    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["show_rating_key"]
        entry = agg.setdefault(
            key,
            {
                "show_rating_key": key,
                "plays": 0,
                "last_played_at": None,
                "_completions": [],
                "_heights": [],
            },
        )
        entry["plays"] += 1
        played = row["played_at"]
        if played and (entry["last_played_at"] is None or played > entry["last_played_at"]):
            entry["last_played_at"] = played
        if row["completion_pct"] is not None:
            entry["_completions"].append(row["completion_pct"])
        if row["stream_height"]:
            entry["_heights"].append(row["stream_height"])
    for entry in agg.values():
        completions = entry.pop("_completions")
        heights = entry.pop("_heights")
        entry["mean_completion"] = (
            sum(completions) / len(completions) if completions else None
        )
        # The typical delivered height, not the best ever seen: one 4K play on a
        # borrowed television should not argue that the whole show needs 4K.
        entry["typical_stream_height"] = (
            sorted(heights)[len(heights) // 2] if heights else None
        )
    return agg
