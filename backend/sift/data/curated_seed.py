"""Starter curated lists (title, year) — resolved to TMDB ids during a scan.

These are a modest, well-known **starter** set, not the full canon. Per the project's
content rules they ship as ``review_status="pending"`` and are meant to be reviewed
and expanded by a human (or replaced by importing a fuller list). They are stored as
title+year so ids come from TMDB search, never fabricated here.

- ``cult``     — cult classics (drives the junk "keep if cult" rule + Missing).
- ``imdb_top`` — widely top-ranked films (Missing "you don't own these").
"""

from __future__ import annotations

CURATED_SEED: dict[str, list[tuple[str, int]]] = {
    "cult": [
        ("The Big Lebowski", 1998),
        ("Blade Runner", 1982),
        ("Donnie Darko", 2001),
        ("Fight Club", 1999),
        ("A Clockwork Orange", 1971),
        ("Reservoir Dogs", 1992),
        ("Trainspotting", 1996),
        ("The Rocky Horror Picture Show", 1975),
        ("Office Space", 1999),
        ("The Thing", 1982),
        ("Fear and Loathing in Las Vegas", 1998),
        ("Eraserhead", 1977),
        ("Akira", 1988),
        ("The Evil Dead", 1981),
        ("Scott Pilgrim vs. the World", 2010),
        ("This Is Spinal Tap", 1984),
        ("Repo Man", 1984),
        ("Brazil", 1985),
        ("Dazed and Confused", 1993),
        ("Groundhog Day", 1993),
    ],
    "imdb_top": [
        ("The Shawshank Redemption", 1994),
        ("The Godfather", 1972),
        ("The Dark Knight", 2008),
        ("The Godfather Part II", 1974),
        ("12 Angry Men", 1957),
        ("Schindler's List", 1993),
        ("The Lord of the Rings: The Return of the King", 2003),
        ("Pulp Fiction", 1994),
        ("The Good, the Bad and the Ugly", 1966),
        ("Forrest Gump", 1994),
        ("Goodfellas", 1990),
        ("The Matrix", 1999),
        ("Se7en", 1995),
        ("Interstellar", 2014),
        ("Parasite", 2019),
        ("The Silence of the Lambs", 1991),
        ("Saving Private Ryan", 1998),
        ("City of God", 2002),
        ("Spirited Away", 2001),
        ("Whiplash", 2014),
    ],
}
