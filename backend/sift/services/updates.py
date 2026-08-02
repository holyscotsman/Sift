"""Am I running the latest Sift?

The running version is compiled in; the newest published one is read from the
repository. Comparing them is what makes the Update button meaningful — without
it you would be clicking "update" with no idea whether there was anything to
update to.

Deliberately narrow: this reads one small public file over HTTPS, caches the
answer, and fails soft. A version check that breaks Settings when GitHub is slow
would be worse than no version check at all.
"""

from __future__ import annotations

import logging
import os
import re
import time

import httpx

log = logging.getLogger("sift.updates")

# Where to look. Overridable so a fork checks its own repo rather than reporting
# itself permanently out of date against someone else's.
DEFAULT_REPO = "holyscotsman/Sift"
_RAW_URL = "https://raw.githubusercontent.com/{repo}/main/pyproject.toml"

# The upstream version moves when a release is merged, not minute to minute, so an
# hour is plenty — and it keeps an idle instance from hammering GitHub.
_CACHE_TTL_SECONDS = 3600.0
_TIMEOUT_SECONDS = 8.0

_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)

# (fetched_at, version) — module-level so it survives across requests.
_cache: tuple[float, str | None] = (0.0, None)


def _repo() -> str:
    return os.environ.get("SIFT_UPDATE_REPO", "").strip() or DEFAULT_REPO


def _parse_version(text: str) -> str | None:
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def version_tuple(value: str) -> tuple[int, ...]:
    """`2607.14.0` -> (2607, 14, 0). Non-numeric parts sort as 0 rather than
    raising, so a hand-edited version can never break the comparison."""
    parts: list[int] = []
    for chunk in value.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(latest: str, running: str) -> bool:
    """True when ``latest`` is strictly ahead. Compares numerically, so 2607.9.0
    correctly reads as older than 2607.14.0 — a string compare would not."""
    return version_tuple(latest) > version_tuple(running)


async def latest_version(*, force: bool = False) -> str | None:
    """The newest published version, or None when it can't be determined.

    None is a normal outcome (no network, rate limited, a private fork) and the
    caller reports "couldn't check" rather than "up to date" — claiming you're
    current when you don't know is the one answer that would actually mislead.
    """
    global _cache
    fetched_at, cached = _cache
    if not force and cached is not None and (time.monotonic() - fetched_at) < _CACHE_TTL_SECONDS:
        return cached
    url = _RAW_URL.format(repo=_repo())
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            version = _parse_version(resp.text)
    except Exception as exc:  # noqa: BLE001 - an unreachable GitHub is not an error here
        log.info("update check skipped: %s", exc)
        return cached  # a stale answer beats none; None if we never had one
    if version:
        _cache = (time.monotonic(), version)
    return version


def reset_cache() -> None:
    """Test seam — the cache is module-level and would leak between tests."""
    global _cache
    _cache = (0.0, None)
