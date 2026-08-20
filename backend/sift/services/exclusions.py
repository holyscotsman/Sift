"""Films that must never be recommended, and the hand corrections that outrank it.

The recommendation lists that ship with Sift are evidence-only: a title is on
them because a public dataset says something measurable about it, never because
anyone here formed an opinion. That works for the canon, and it needs a
counterpart — because "everything with a theatrical release, however bad" also
lets in a very large number of things that never had one.

``exclude_list.json`` is that counterpart, and it is evidence-only in the same
way: IMDb's own ``titleType`` marks a release as ``tvMovie`` or ``video``, which
is a fact about how the film was distributed rather than a judgement about
whether it is any good. Direct-to-video sequels and TV movies come off the list;
theatrical flops stay on it, exactly as asked.

``list_overrides.json`` is the one place a judgement call belongs, and it
outranks everything. The generator never writes it, so a hand correction survives
every rebuild of the generated lists.

**Matching is deliberately asymmetric.** Both files are keyed on IMDb id, which
resolves exactly. Where a candidate carries one, that id decides on its own — an
id absent from the exclusion list means the list has nothing to say about *that
film*, and falling through to a title match would let a different film with the
same name answer for it. Title-and-year matching is only a fallback for
candidates that arrive with no id at all, which is what TMDB discovery and every
AI provider hand back.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger("sift.exclusions")

_DATA = Path(__file__).resolve().parent.parent / "data"
_EXCLUDE = _DATA / "exclude_list.json"
_CANON = _DATA / "canon_25k.json"
_OVERRIDES = _DATA / "list_overrides.json"

_PUNCT = re.compile(r"[^a-z0-9]+")
# Apostrophes are *deleted* rather than turned into a space, because sources
# disagree about them constantly — "Simba's Pride" and "Simbas Pride" are one
# film, and replacing the mark with a space makes them two.
_APOSTROPHE = re.compile(r"['\u2018\u2019\u02bc`]")


def normalize(title: str) -> str:
    """A title reduced to what two spellings of the same film have in common.

    Case, punctuation and spacing only. Leading articles are deliberately *kept*:
    dropping "The" collides "The Thing" with "Thing", and a collision here
    silently removes a film from every recommendation surface at once.
    """
    return _PUNCT.sub(" ", _APOSTROPHE.sub("", title.casefold())).strip()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():  # pragma: no cover - both files ship with the package
        log.warning("list file missing at %s", path)
        return {}
    return dict(json.loads(path.read_text()))


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    """Both files, parsed and indexed once per process."""
    excluded_ids: set[str] = set()
    excluded_titles: set[tuple[str, int]] = set()
    for row in _load(_EXCLUDE).get("titles", []):
        imdb_id = row.get("imdb_id")
        if imdb_id:
            excluded_ids.add(str(imdb_id))
        title, year = row.get("title"), row.get("year")
        if title and isinstance(year, int):
            excluded_titles.add((normalize(str(title)), year))

    overrides = _load(_OVERRIDES)

    def _override(key: str) -> tuple[set[str], set[tuple[str, int]]]:
        ids: set[str] = set()
        titles: set[tuple[str, int]] = set()
        for row in (overrides.get(key) or {}).get("titles", []):
            if not isinstance(row, dict):
                continue
            imdb_id = row.get("imdb_id")
            if imdb_id:
                ids.add(str(imdb_id))
            title, year = row.get("title"), row.get("year")
            if title and isinstance(year, int):
                titles.add((normalize(str(title)), year))
        return ids, titles

    # Title-and-year keys the *canon* also claims. Forty-seven of them, measured on
    # the shipped files: films like *Home Alone 2* and *Anastasia*, where a
    # theatrical release and a same-named TV movie share a year. The two lists are
    # disjoint by IMDb id — zero overlap, by construction — so this only ever
    # matters for a candidate that arrives with no id, which is exactly what TMDB
    # discovery and every AI provider hand back.
    contested: set[tuple[str, int]] = set()
    for row in _load(_CANON).get("titles", []):
        title, year = row.get("title"), row.get("year")
        if title and isinstance(year, int):
            key = (normalize(str(title)), year)
            if key in excluded_titles:
                contested.add(key)

    always_ids, always_titles = _override("always_recommend")
    never_ids, never_titles = _override("never_recommend")
    return {
        "contested_titles": contested,
        "excluded_ids": excluded_ids,
        "excluded_titles": excluded_titles,
        "always_ids": always_ids,
        "always_titles": always_titles,
        "never_ids": never_ids,
        "never_titles": never_titles,
    }


def reload() -> None:
    """Forget the parsed files. For tests and for an edited overrides file."""
    _index.cache_clear()


def _matches(
    ids: set[str],
    titles: set[tuple[str, int]],
    imdb_id: str | None,
    title: str | None,
    year: int | None,
) -> bool:
    if imdb_id and imdb_id in ids:
        return True
    if imdb_id:
        # The id resolved and said nothing. A title match now would be a
        # different film answering for this one.
        return False
    if title and year is not None:
        return (normalize(title), year) in titles
    return False


def excluded(
    *, imdb_id: str | None = None, title: str | None = None, year: int | None = None
) -> bool:
    """Should this candidate be kept off every recommendation surface?

    Precedence, highest first: the ``never_recommend`` override, the
    ``always_recommend`` override, then the generated exclusion list. A film named
    in both override sections is excluded — a hand-written "never" is a decision
    someone made on purpose and the safer of the two to honour.
    """
    idx = _index()
    if _matches(idx["never_ids"], idx["never_titles"], imdb_id, title, year):
        return True
    if _matches(idx["always_ids"], idx["always_titles"], imdb_id, title, year):
        return False
    # A candidate with no id whose title and year the canon *also* claims is
    # ambiguous, and ambiguity resolves toward keeping it. The two errors are not
    # the same size: a wrong exclusion silently removes a good film from every
    # surface for ever, and nobody can see that it happened. A wrong inclusion
    # offers one bad suggestion, which the owner ignores in a second.
    if (
        not imdb_id
        and title
        and year is not None
        and (normalize(title), year) in idx["contested_titles"]
    ):
        return False
    return _matches(idx["excluded_ids"], idx["excluded_titles"], imdb_id, title, year)


def always_recommend() -> list[dict[str, Any]]:
    """Hand-added titles the generated canon missed, as raw rows.

    Returned rather than applied here, because the only sensible place to *use*
    them is the canon seeder — this module knows what the files say, not what the
    database should look like.
    """
    rows = (_load(_OVERRIDES).get("always_recommend") or {}).get("titles", [])
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("title")]


def never_recommend_keys() -> tuple[set[str], set[tuple[str, int]]]:
    """``(imdb ids, (normalised title, year) pairs)`` the owner has struck out.

    Exposed as raw keys so the canon seeder can prune rows that are *already*
    stored. Without that, a hand correction only ever affects candidates arriving
    from outside and is silently inert against the twenty-five thousand titles
    that shipped — which is most of the list, and the half someone is most likely
    to be looking at when they reach for the file.
    """
    idx = _index()
    return set(idx["never_ids"]), set(idx["never_titles"])


def counts() -> dict[str, int]:
    """Sizes of the loaded lists, for the health surface and for tests."""
    idx = _index()
    return {
        "excluded": len(idx["excluded_ids"]),
        "always_recommend": len(idx["always_ids"]) + len(idx["always_titles"]),
        "never_recommend": len(idx["never_ids"]) + len(idx["never_titles"]),
    }
