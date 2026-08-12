"""Which Plex libraries Sift reads, and whether each is films or television.

Plex's own ``type`` is nearly right and wrong in one important place. A **Home
Videos** or **Other Videos** library is type ``movie``, so left alone Sift ingests
family footage as films — which puts it in the removal queue, in the film counts,
and, worst of the three, in the bitrate baselines that every size verdict is
measured against. A few hundred phone clips are enough to drag the median for
"1080p h264" somewhere meaningless.

What separates those libraries is not their type but their **agent**: a library
with no metadata agent has no ratings, no cast and nothing to match against TMDB.
Nothing in Sift can say anything useful about its contents, so the default is to
leave it alone. That is a fact about the library rather than a guess about its
name — "Home Videos" in another language, or called "Camcorder", is caught just
the same.

Everything here is overridable. Plex's type is a default, not a verdict: a
Cartoons, Anime or Game Shows library is a show library and is treated as
television without anyone having to say so, and where Plex has it wrong the owner
can say `movie`, `show` or `ignore` and be believed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MOVIE = "movie"
SHOW = "show"
IGNORE = "ignore"

# Plex reports this agent for a library with no metadata matching at all — the
# "Other Videos"/personal-media case.
_NO_AGENT = ("com.plexapp.agents.none", "tv.plex.agents.none", "none", "")

# Section types Sift has no use for. Music and photos are not video.
_UNUSABLE_TYPES = ("artist", "photo")


@dataclass(frozen=True)
class SectionPlan:
    """What Sift will do with one Plex library, and why."""

    key: str
    title: str
    plex_type: str
    agent: str | None
    kind: str  # movie | show | ignore
    reason: str
    # True when the owner set this explicitly rather than it being inferred.
    overridden: bool

    @property
    def scanned(self) -> bool:
        return self.kind in (MOVIE, SHOW)


def plan_section(section: dict[str, Any], overrides: dict[str, str] | None = None) -> SectionPlan:
    """Decide how to treat one library."""
    title = str(section.get("title") or "")
    plex_type = str(section.get("type") or "")
    agent = section.get("agent")
    key = str(section.get("key") or "")

    override = (overrides or {}).get(title)
    if override in (MOVIE, SHOW, IGNORE):
        return SectionPlan(
            key=key,
            title=title,
            plex_type=plex_type,
            agent=agent,
            kind=override,
            reason="set by you",
            overridden=True,
        )

    if plex_type in _UNUSABLE_TYPES:
        return SectionPlan(
            key, title, plex_type, agent, IGNORE, f"{plex_type} library, not video", False
        )

    # Present *and* explicitly none. A section that simply does not report an
    # agent — an older Plex, a field that moved — must fall through to its type
    # rather than be dropped: inferring "personal media" from silence would make
    # a scan quietly read nothing at all, which looks identical to a working scan
    # of an empty library.
    if agent is not None and str(agent).lower() in _NO_AGENT:
        # No agent means no ratings, no cast, nothing to match. Reading it would
        # add rows nothing can judge and skew the size baselines.
        return SectionPlan(
            key,
            title,
            plex_type,
            agent,
            IGNORE,
            "personal media — no metadata agent, so nothing here can be judged",
            False,
        )

    if plex_type == SHOW:
        return SectionPlan(key, title, plex_type, agent, SHOW, "a show library", False)
    if plex_type == MOVIE:
        return SectionPlan(key, title, plex_type, agent, MOVIE, "a film library", False)
    return SectionPlan(key, title, plex_type, agent, IGNORE, f"unknown type {plex_type!r}", False)


def plan(
    sections: list[dict[str, Any]], overrides: dict[str, str] | None = None
) -> list[SectionPlan]:
    return [plan_section(s, overrides) for s in sections]
