"""Why a film is being recommended, counted from what the owner already has.

The Missing list was ranked ``(tier, -votes, tmdb_id)``: the canon's judgement
first, then fame. That is a defensible global ranking and it is the same ranking
for everybody, which is the problem — it recommends the most famous unowned film
in the strongest tier, over and over, to a person whose library says plainly what
they actually watch.

The original ask was for suggestions "sorted by what is suggested the most", and
the obvious reading — count how many sources vouch for a title — does not survive
contact with the data: **24,417 of the 25,000 shipped entries carry exactly one
source**, so that ranking is a near-universal tie broken by whatever comes next.

So the reasons are counted from a different place: the library. A director whose
films are already on the shelf is a reason. A genre the shelf is full of is a
weaker reason. Both are facts about *this* household, both are arithmetic over
stored rows, and both can be stated in words on the card — which matters, because
a recommendation nobody can explain is one nobody trusts.

**No model is consulted anywhere in this file.** Ranking is arithmetic; that is
the standing rule, and it is also why the scores are reproducible.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# How many films by one director it takes before the shelf is making a statement
# rather than an accident. One is a coincidence — plenty of people own exactly one
# Kubrick. Two is a pattern.
DIRECTOR_FLOOR = 2

# Genres are broad and everybody owns Drama, so a genre only counts as a reason
# when the library over-indexes on it well past its share of the canon.
GENRE_SHARE_FLOOR = 0.18

# Points per reason. Directors outweigh genres deliberately: "you own three of
# theirs" is a far narrower claim than "you own a lot of thrillers", and a ranking
# that let genre outvote it would bury the specific under the general.
DIRECTOR_POINTS = 3
GENRE_POINTS = 1

# IMDb and TMDB disagree on the name of the same genre. Neither vocabulary is
# authoritative here, so they are folded into one on comparison rather than
# rewritten at rest — the stored rows stay traceable to the line they came from.
_GENRE_ALIASES = {
    "science fiction": "sci-fi",
    "tv movie": "tvmovie",
    "musical": "music",
}


def _fold(genre: str) -> str:
    key = genre.strip().lower()
    return _GENRE_ALIASES.get(key, key)


@dataclass(frozen=True)
class Profile:
    """What the library says about its owner. Built once, applied to many rows."""

    directors: Counter[str] = field(default_factory=Counter)
    genre_share: dict[str, float] = field(default_factory=dict)
    owned: int = 0

    @property
    def is_empty(self) -> bool:
        """An empty library cannot vouch for anything.

        Worth its own name because the fallback matters: with no profile every
        candidate scores zero, the affinity term drops out, and the ranking is
        exactly the tier-and-fame ordering it was before. A new install is not
        given a worse list than it had — it is given the same one.
        """
        return self.owned == 0


def build_profile(
    owned_genres: list[list[str]],
    owned_directors: list[list[str]],
) -> Profile:
    """Count what is on the shelf.

    Takes plain lists rather than a session on purpose: this is arithmetic, and
    arithmetic that needs a database to be tested is arithmetic that mostly does
    not get tested.
    """
    owned = len(owned_genres)
    if owned == 0:
        return Profile()

    directors: Counter[str] = Counter()
    for names in owned_directors:
        # A film counts once per director, never twice for the same name — a
        # duplicated row in the source would otherwise manufacture a pattern.
        for name in set(names):
            if name:
                directors[name] += 1

    genres: Counter[str] = Counter()
    for names in owned_genres:
        for name in set(names):
            if name:
                genres[_fold(name)] += 1

    return Profile(
        directors=directors,
        genre_share={g: n / owned for g, n in genres.items()},
        owned=owned,
    )


def reasons_for(
    profile: Profile,
    *,
    tier: int,
    genres: list[str] | None,
    directors: list[str] | None,
) -> list[str]:
    """The nameable reasons to suggest this film, strongest first.

    Returns the words themselves rather than a number, because the number is
    derived from them and the words are what goes on the card. A ranking that can
    only produce a score is a ranking nobody can argue with.
    """
    out: list[str] = []
    # Deliberately vague about *which* list vouches for it. The built-in list is
    # meant to be invisible — the owner asked for suggestions, not for a tour of
    # the machinery — so these say how strong the claim is and stop there. The
    # reasons that follow are about the owner's own shelf, which is the half they
    # can actually check.
    if tier <= 1:
        out.append("Widely regarded as essential")
    elif tier == 2:
        out.append("Widely held to be worth owning")
    elif tier == 3:
        out.append("Well regarded")

    for name in directors or []:
        seen = profile.directors.get(name, 0)
        if seen >= DIRECTOR_FLOOR:
            out.append(f"You own {seen} films by {name}")

    for genre in genres or []:
        share = profile.genre_share.get(_fold(genre), 0.0)
        if share >= GENRE_SHARE_FLOOR:
            out.append(f"{genre} is {share:.0%} of your library")

    return out


# What the canon's own judgement is worth, in the same currency as the rest. A
# tier-1 film starts four points ahead of a tier-4 one — enough that canon leads
# a library with nothing to say, and little enough that two films by a director
# the owner clearly loves can overtake it. Which is the point: "you own three of
# theirs" is a better reason than "somebody's list names it".
TIER_POINTS = {1: 4, 2: 2, 3: 1}


def score(
    profile: Profile,
    *,
    tier: int,
    genres: list[str] | None,
    directors: list[str] | None,
) -> int:
    """Total weight of the reasons to suggest this film.

    Tier is included rather than left to the sort key, because a single ordering
    that mixes both is the only way a tier-4 film with a real personal connection
    can outrank a tier-1 film with none — and it should. Leaving tier as the
    primary sort and affinity as a tiebreak would produce the same list as before
    with the reasons written on it, which is a worse outcome dressed as a better
    one.

    With an empty library every library term is zero and the total collapses to
    the tier points alone, which is *exactly* the ordering this replaced. A new
    install gets the list it always got, not a worse one.
    """
    points = TIER_POINTS.get(tier, 0)
    if profile.is_empty:
        return points
    for name in directors or []:
        seen = profile.directors.get(name, 0)
        if seen >= DIRECTOR_FLOOR:
            # More films by the same director is a stronger claim, but not
            # without limit — someone who owns thirty Hitchcocks does not need
            # every remaining Hitchcock ahead of everything else on the list.
            points += DIRECTOR_POINTS * min(seen, 4)
    for genre in genres or []:
        if profile.genre_share.get(_fold(genre), 0.0) >= GENRE_SHARE_FLOOR:
            points += GENRE_POINTS
    return points


# How much each earlier film by the same director costs the next one. Two points
# per place, so a director bonus of twelve is spent after six films and the
# seventh ranks on its tier alone.
DIRECTOR_RUN_PENALTY = 2


def spread(
    rows: list[tuple[str, int, list[str], int]],
) -> dict[str, int]:
    """Stop one director owning the top of the list.

    Takes ``(key, score, directors, votes)`` and returns adjusted scores.

    Without this, a shelf with five Kurosawa films on it produced **twenty-five
    consecutive Kurosawa films** at the head of the first page — measured, not
    feared. Which is not wrong, exactly: every one of them is a film the owner
    plausibly wants, and each carries a real reason. It is just not a
    recommendation list. It is a filmography, and the person has to scroll past
    all of it to discover the list contains anything else.

    So each film after the first by a given director pays a small, fixed toll.
    The best few still lead — that is the whole point of noticing the pattern —
    and by the seventh the director bonus is spent and it ranks on its tier like
    everything else. Deeper cuts by a beloved director are still *on* the list,
    still ahead of films with nothing to recommend them, just no longer stacked
    twenty-five deep before anything else gets a turn.

    Order within a director's own films is by score then votes then key, so this
    is deterministic: the same library produces the same list every time.
    """
    seen: Counter[str] = Counter()
    adjusted: dict[str, int] = {}
    # Sorted so the toll is charged in a defined order — highest first, so the
    # film a director is best known for is the one that keeps its full weight.
    for key, points, directors, _votes in sorted(
        rows, key=lambda r: (-r[1], -r[3], r[0])
    ):
        penalty = 0
        for name in directors or []:
            penalty = max(penalty, seen[name] * DIRECTOR_RUN_PENALTY)
            seen[name] += 1
        adjusted[key] = max(0, points - penalty)
    return adjusted
