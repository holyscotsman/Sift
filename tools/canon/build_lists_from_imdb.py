#!/usr/bin/env python3
"""Rebuild the recommendation canon and the exclusion list from IMDb's datasets.

Both lists are *derived from evidence*, never hand-authored. That is the rule this
script exists to enforce: no title appears in either file because somebody thought
it belonged there, only because the data says so, and every field is traceable to a
row in a public dataset.

    Source: IMDb Datasets — https://datasets.imdbws.com/
            title.basics.tsv.gz, title.ratings.tsv.gz
            Free for personal and non-commercial use. Not affiliated with IMDb.

Usage:

    python tools/canon/build_lists_from_imdb.py \
        --basics title.basics.tsv.gz --ratings title.ratings.tsv.gz

What it produces
----------------

**canon_25k.json** — films worth recommending. Extends the existing 10,000 rather
than replacing it: every entry already in ``canon_10k.json`` is carried over with
its tier and pillars intact, because those came from Criterion, the cult canon,
award records and the film registry, and no ranking of IMDb votes improves on them.
The remaining slots are filled by weighted rating, deepest first.

**exclude_list.json** — films that should never be recommended. Membership is a
*fact about the release*, not a judgement about the film: IMDb classifies these as
``video`` (direct-to-video) or ``tvMovie``. Nothing that had a theatrical run is in
here, however badly it was received — a bad theatrical film is still a film the
owner might want, and it stays in the canon at the bottom of the ranking rather
than being excluded.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "backend" / "sift" / "data"

# A film needs enough votes for its rating to mean anything, and enough to suggest
# it actually reached an audience. Below this the rating is a handful of people.
CANON_VOTE_FLOOR = 1_000
# The exclusion list is not about quality, so its floor is only "somebody saw it" —
# low enough to catch the long tail of direct-to-video, high enough to skip noise.
EXCLUDE_VOTE_FLOOR = 100

# A feature, not a featurette. IMDb files hour-long documentaries and TV specials
# as `movie`, and without this the canon fills up with 50-minute pieces that
# nobody is looking to own a copy of.
FEATURE_MINUTES = 60

# The escape hatch on the exclusion rule, and it is evidence rather than taste: a
# direct-to-video title with a large audience *and* a high rating is not schlock,
# whatever its release channel. Batman: Under the Red Hood, The Animatrix and
# Spielberg's Duel all live here. Without it the rule quietly deletes the best
# fifty films it touches.
WELL_REGARDED_RATING = 7.0
WELL_REGARDED_VOTES = 25_000

TARGET = 25_000

# IMDb's own weighted-rating shape, and the prior the existing file documents.
WR_M = 25_000

# Tier bands for newly filled entries, by rank within the fill. The existing
# pillars keep the tiers they arrived with; these only apply to the extension,
# which by construction sits below them.
NEW_TIER_BANDS = ((0.25, 2), (0.55, 3))  # then tier 4


def read_ratings(path: Path) -> dict[str, tuple[float, int]]:
    out: dict[str, tuple[float, int]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            tconst, average, votes = line.rstrip("\n").split("\t")
            out[tconst] = (float(average), int(votes))
    return out


def read_titles(
    path: Path, ratings: dict[str, tuple[float, int]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(theatrical features, direct-to-video and TV films) — both rated and non-adult."""
    features: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            row = line.rstrip("\n").split("\t")
            tconst, kind, title = row[0], row[1], row[2]
            adult, start = row[4], row[5]
            if adult == "1" or tconst not in ratings:
                continue
            if kind not in ("movie", "video", "tvMovie"):
                continue
            year = int(start) if start.isdigit() else None
            runtime = int(row[7]) if len(row) > 7 and row[7].isdigit() else None
            rating, votes = ratings[tconst]
            entry = {
                "imdb_id": tconst,
                "title": title,
                "year": year,
                "rating": rating,
                "votes": votes,
            }
            if kind == "movie":
                # An unknown runtime is kept: absent data is not evidence of a
                # featurette, and the older pillars carry films with no runtime.
                if votes >= CANON_VOTE_FLOOR and (runtime is None or runtime >= FEATURE_MINUTES):
                    features.append(entry)
            elif votes >= EXCLUDE_VOTE_FLOOR:
                if rating >= WELL_REGARDED_RATING and votes >= WELL_REGARDED_VOTES:
                    continue  # widely seen and well liked — not what this list is for
                entry["kind"] = kind
                excluded.append(entry)
    return features, excluded


def weighted(rating: float, votes: int, mean: float) -> float:
    """IMDb's weighted rating: pulls a thinly-voted film toward the mean."""
    return (votes / (votes + WR_M)) * rating + (WR_M / (votes + WR_M)) * mean


def build_canon(features: list[dict[str, Any]], existing: dict[str, Any]) -> dict[str, Any]:
    kept = list(existing["titles"])
    have = {e["imdb_id"] for e in kept if e.get("imdb_id")}
    have_titles = {(e.get("title"), e.get("year")) for e in kept if not e.get("imdb_id")}

    mean = sum(f["rating"] for f in features) / len(features)
    for f in features:
        f["wr"] = weighted(f["rating"], f["votes"], mean)
    features.sort(key=lambda f: (-f["wr"], -f["votes"], f["imdb_id"]))

    room = TARGET - len(kept)
    fill = [
        f
        for f in features
        if f["imdb_id"] not in have and (f["title"], f["year"]) not in have_titles
    ][:room]

    for rank, f in enumerate(fill):
        share = rank / max(1, len(fill))
        tier = 4
        for edge, value in NEW_TIER_BANDS:
            if share < edge:
                tier = value
                break
        kept.append(
            {
                "title": f["title"],
                "year": f["year"],
                "sources": ["imdb_wr"],
                "imdb_id": f["imdb_id"],
                "rating": f["rating"],
                "votes": f["votes"],
                "tier": tier,
            }
        )

    out = dict(existing)
    out["name"] = "canon_25k"
    out["version"] = datetime.now(UTC).strftime("%Y-%m-%d")
    out["count"] = len(kept)
    out["titles"] = kept
    pillars = dict(existing.get("pillars") or {})
    pillars["imdb_wr"] = (
        f"Theatrical-consensus fill from official IMDb datasets: features with "
        f">={CANON_VOTE_FLOOR} votes ranked by weighted rating (m={WR_M:,}, "
        f"C={mean:.3f}), tiered 2-4 by fill rank. Extended from 10,000 to "
        f"{TARGET:,}; the vote floor is deliberately a floor on *reach*, not on "
        f"quality, so a poorly received theatrical release is still carried — it "
        f"simply ranks last."
    )
    out["pillars"] = pillars
    out["source"] = (
        "IMDb Datasets (https://datasets.imdbws.com/), title.basics + title.ratings. "
        "Free for personal and non-commercial use. Not affiliated with IMDb."
    )
    out["generated_by"] = "tools/canon/build_lists_from_imdb.py"
    return out


def build_exclusions(excluded: list[dict[str, Any]]) -> dict[str, Any]:
    excluded.sort(key=lambda e: (-e["votes"], e["imdb_id"]))
    return {
        "name": "exclude_list",
        "version": datetime.now(UTC).strftime("%Y-%m-%d"),
        "count": len(excluded),
        "rule": (
            "IMDb classifies the title as `video` (direct-to-video) or `tvMovie`. "
            "That is a fact about how the film was released, not an opinion about "
            "whether it is any good — which is the point: nothing here was judged, "
            "it was categorised at publication."
        ),
        "not_the_rule": (
            "A low rating is NOT grounds for exclusion. A theatrical release stays "
            "recommendable however badly it was received; people watch those on "
            "purpose. Quality is expressed by ranking, never by removal."
        ),
        "escape_hatch": (
            f"A direct-to-video or TV title rated >={WELL_REGARDED_RATING} with "
            f">={WELL_REGARDED_VOTES:,} votes is NOT excluded. A large audience that "
            "rates it highly is evidence it is not schlock, whatever channel it came "
            "out on — this is what keeps Duel, The Animatrix and the DC animated "
            "features off the list."
        ),
        "overrides": (
            "Hand corrections live in `list_overrides.json`, which this script never "
            "writes. A cult classic that happens to be direct-to-video belongs there."
        ),
        "source": (
            "IMDb Datasets (https://datasets.imdbws.com/), title.basics + title.ratings. "
            "Free for personal and non-commercial use. Not affiliated with IMDb."
        ),
        "generated_by": "tools/canon/build_lists_from_imdb.py",
        "titles": excluded,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basics", type=Path, required=True)
    parser.add_argument("--ratings", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DATA)
    args = parser.parse_args()

    ratings = read_ratings(args.ratings)
    features, excluded = read_titles(args.basics, ratings)
    existing = json.loads((DATA / "canon_10k.json").read_text())

    canon = build_canon(features, existing)
    exclusions = build_exclusions(excluded)

    (args.out / "canon_25k.json").write_text(json.dumps(canon, indent=1, ensure_ascii=False))
    (args.out / "exclude_list.json").write_text(
        json.dumps(exclusions, indent=1, ensure_ascii=False)
    )

    print(f"rated titles           {len(ratings):,}")
    print(f"theatrical features    {len(features):,} (>= {CANON_VOTE_FLOOR:,} votes)")
    print(f"canon                  {canon['count']:,}")
    print(f"exclusions             {exclusions['count']:,} (>= {EXCLUDE_VOTE_FLOOR} votes)")


if __name__ == "__main__":
    main()
