"""TMDB's public movie genre ids → names (stable, documented API constants).

Discovery payloads carry ``genre_ids`` only; this map lets the recommender compare
them against the library's genre names without an extra API call per candidate.
"""

from __future__ import annotations

TMDB_GENRES: dict[int, str] = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}
