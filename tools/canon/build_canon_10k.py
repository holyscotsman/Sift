#!/usr/bin/env python3
"""Double the canon to 10,000.

Additions target watch-desire coverage ("the movie I want tonight"): ranked by
fame (vote volume), gated by quality floors:
  - rating >= 6.0 (no bad movies)
  - non-English-original (originalTitle != primaryTitle proxy): rating >= 7.0
    AND votes >= 25,000 (no low-rated international padding)
  - votes >= 10,000 (below that, nobody is reaching for it on movie night)
Existing 5,000 (criterion/cult/consensus) kept verbatim.
"""

import os

# Where the intermediate canon artefacts live. These are offline provenance
# scripts, run by hand outside the app, so the working directory is a parameter
# rather than a constant baked into the source.
WORK_DIR = os.environ.get("CANON_WORK_DIR", ".")


def work_path(name: str) -> str:
    return os.path.join(WORK_DIR, name)

import csv, gzip, json, re, sys, unicodedata

def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)

base = json.load(open(work_path("canon_expanded.json")))
existing = base["titles"]
taken_ids = {e["imdb_id"] for e in existing if "imdb_id" in e}
taken_ny = {(norm(e["title"]), e["year"]) for e in existing}
print(f"existing: {len(existing)}", file=sys.stderr)

ratings = {}
with gzip.open("/tmp/ratings.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t"); next(rd)
    for tconst, rating, votes in rd:
        v = int(votes)
        if v >= 10000:
            ratings[tconst] = (float(rating), v)

cands = []
with gzip.open("/tmp/basics.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE); next(rd)
    for row in rd:
        try:
            tconst, ttype, primary, original, adult, y, _, rt, genres = row
        except ValueError:
            continue
        if ttype != "movie" or adult == "1" or tconst not in ratings:
            continue
        if tconst in taken_ids or not y.isdigit() or not rt.isdigit():
            continue
        y, rtm = int(y), int(rt)
        if not (1915 <= y <= 2026) or not (70 <= rtm <= 400):
            continue
        rating, votes = ratings[tconst]
        intl = norm(original) != norm(primary)
        if rating < 6.0:
            continue
        if intl and (rating < 7.0 or votes < 25000):
            continue
        if (norm(primary), y) in taken_ny:
            continue
        cands.append({"title": primary, "year": y, "imdb_id": tconst,
                      "rating": rating, "votes": votes, "intl": intl})
print(f"candidates passing floors: {len(cands)}", file=sys.stderr)

cands.sort(key=lambda c: (-c["votes"], -c["rating"], c["imdb_id"]))
TARGET_ADD = 10000 - len(existing)
adds, seen_ny = [], set()
for c in cands:
    if len(adds) >= TARGET_ADD:
        break
    key = (norm(c["title"]), c["year"])
    if key in seen_ny:
        continue
    seen_ny.add(key)
    rank = len(adds) + 1
    tier = 2 if rank <= 1000 else 3 if rank <= 3000 else 4
    adds.append({"title": c["title"], "year": c["year"], "imdb_id": c["imdb_id"],
                 "rating": c["rating"], "votes": c["votes"],
                 "sources": ["popular"], "tier": tier})
print(f"added: {len(adds)}; tail votes: {adds[-1]['votes']:,}; "
      f"tail example: {adds[-1]['title']} ({adds[-1]['year']}) {adds[-1]['rating']}", file=sys.stderr)

intl_added = sum(1 for a in adds if any(c["imdb_id"] == a["imdb_id"] and c["intl"] for c in cands))
full = existing + adds
out = dict(base)
out.update({
    "name": "canon_10k",
    "version": "2026-08-14.3",
    "count": len(full),
    "titles": full,
})
out["pillars"] = dict(base["pillars"])
out["pillars"]["popular"] = ("Watch-desire coverage: fame-ranked (votes desc) IMDb features, "
                             "rating >= 6.0, votes >= 10k; non-English-original requires rating >= 7.0 "
                             "and votes >= 25k. Tiered 2/3/4 by fame rank.")
with open(work_path("canon_10k.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)

# plain-text list, alphabetical ignoring leading articles
lines = sorted((f"{e['title']} ({e['year']})" for e in full),
               key=lambda s: norm(s.rsplit(" (", 1)[0]) or s.lower())
with open(work_path("canon_10k_list.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"SIFT CANON - {len(full)} MOVIES\n")
    fh.write("Criterion Collection + cult classics + acclaimed consensus + popular favorites\n")
    fh.write("Alphabetical (ignoring The/A/An).\n\n")
    fh.write("\n".join(lines) + "\n")
print(f"wrote canon_10k.json and canon_10k_list.txt ({len(full)} titles, {intl_added} intl in additions)", file=sys.stderr)
