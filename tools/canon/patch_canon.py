#!/usr/bin/env python3
"""Resolve every canon-source entry against IMDb, patch genuine gaps, re-verify.

Alias misses (different title form, same film) resolve via imdb_id. True gaps
enter under a canon-source exemption: no vote floor (>=200 sanity only), but
the owner's rating >= 6.0 floor holds — canonical-but-bad titles are reported,
not added. List stays exactly 10,000 by displacing the lowest-fame 'popular'
entries."""
import csv, gzip, json, re, sys, unicodedata
from collections import defaultdict

YEAR_LO, YEAR_HI = 1890, 2026
LINK = re.compile(r"''+\[\[([^\]|]+)(?:\|([^\]]+))?\]\]''+")
SORTNAME = re.compile(r"\{\{sortname\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}")

def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = re.sub(r"^(the|a|an|le|la|les|el|il|der|die|das)\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)

def clean(target, display):
    t = (display or target).strip()
    return re.sub(r"\s*\((?:\d{4}\s+)?film\)$", "", t).strip()

def title_from(text):
    m = LINK.search(text)
    if m: return clean(m.group(1), m.group(2))
    sn = SORTNAME.search(text)
    if sn: return f"{sn.group(1).strip()} {sn.group(2).strip()}"
    return None

def parse_page(wt):
    out = set()
    for line in wt.splitlines():
        s = line.strip()
        if not (s.startswith("|") or s.startswith("*") or s.startswith("#")): continue
        if "series (" in s.lower(): continue        # franchise-series rows on box-office page
        t = title_from(s)
        if not t: continue
        ys = [int(y) for y in re.findall(r"\b(1[89]\d\d|20[0-2]\d)\b", s)]
        if ys: out.add((t, ys[0]))
    for block in re.split(r"^\|-.*$", wt, flags=re.M):
        t = title_from(block)
        if not t: continue
        ys = []
        for line in block.splitlines():
            m = re.match(r"^\|\s*(1[89]\d\d|20[0-2]\d)\s*(?:\{\{|$|\|)", line.strip())
            if m: ys.append(int(m.group(1)))
        if not ys:
            ys = [int(y) for y in re.findall(r"\b(1[89]\d\d|20[0-2]\d)\b", block)][:1]
        if ys: out.add((t, ys[0]))
    return {(t, y) for (t, y) in out if YEAR_LO <= y <= YEAR_HI}

SOURCES = {
    "afi_1998": ("afi", "AFI 100 Years...100 Movies (1998)"),
    "afi_2007": ("afi", "AFI 100 Years...100 Movies (2007)"),
    "sight_sound": ("sight_sound", "Sight & Sound 2022"),
    "oscar_wins": ("oscar_winner", "Academy Award-winning films"),
    "box_office": ("box_office", "Highest-grossing films"),
    "film_registry": ("film_registry", "National Film Registry"),
    "palme_dor": ("festival_top_prize", "Palme d'Or"),
    "golden_lion": ("festival_top_prize", "Golden Lion"),
    "golden_bear": ("festival_top_prize", "Golden Bear"),
    "bfi_top100": ("bfi_100", "BFI Top 100 British films"),
}

# ── IMDb full movie index ─────────────────────────────────────────────────────
ratings = {}
with gzip.open("/tmp/ratings.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t"); next(rd)
    for tconst, rating, votes in rd:
        ratings[tconst] = (float(rating), int(votes))

by_ny = defaultdict(list)      # (norm, year) -> [meta]
by_n = defaultdict(list)       # norm -> [meta]
with gzip.open("/tmp/basics.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE); next(rd)
    for row in rd:
        try:
            tconst, ttype, primary, original, adult, y, _, rt, genres = row
        except ValueError:
            continue
        if ttype != "movie" or adult == "1" or not y.isdigit(): continue
        y = int(y)
        if not (YEAR_LO <= y <= YEAR_HI): continue
        r, v = ratings.get(tconst, (None, 0))
        meta = {"id": tconst, "title": primary, "year": y, "rating": r, "votes": v,
                "runtime": int(rt) if rt.isdigit() else None}
        for n in {norm(primary), norm(original)}:
            if n:
                by_ny[(n, y)].append(meta)
                by_n[n].append(meta)

def resolve(title, year):
    n = norm(title)
    cands = []
    for dy in range(-3, 4):
        cands += by_ny.get((n, year + dy), [])
    if not cands:
        pool = by_n.get(n, [])
        if len({m["id"] for m in pool}) == 1:
            cands = pool
    if not cands: return None
    return max({m["id"]: m for m in cands}.values(), key=lambda m: (m["votes"], m["id"]))

# ── current canon ─────────────────────────────────────────────────────────────
canon = json.load(open("/home/claude/canon_10k.json"))
titles = canon["titles"]
canon_ids = {t["imdb_id"] for t in titles if "imdb_id" in t}
canon_ny = set()
for t in titles:
    for dy in (-1, 0, 1):
        canon_ny.add((norm(t["title"]), t["year"] + dy))

# ── sweep, resolve, classify ──────────────────────────────────────────────────
report, gaps, excluded_low, unresolved = {}, {}, [], defaultdict(int)
for key, (tag, label) in SOURCES.items():
    wt = open(f"/tmp/src_{key}.wikitext").read()
    entries = parse_page(wt)
    stats = {"label": label, "parsed": len(entries), "covered": 0, "gap": 0,
             "nonfeature": 0, "below_floor": 0, "unresolved": 0}
    for (t, y) in sorted(entries):
        if (norm(t), y) in canon_ny:
            stats["covered"] += 1; continue
        m = resolve(t, y)
        if m is None:
            stats["unresolved"] += 1; unresolved[key] += 1; continue
        if m["id"] in canon_ids:
            stats["covered"] += 1; continue
        if m["runtime"] is None or not (70 <= m["runtime"] <= 400) or m["votes"] < 200 or m["rating"] is None:
            stats["nonfeature"] += 1; continue
        if m["rating"] < 6.0:
            stats["below_floor"] += 1
            excluded_low.append((m["title"], m["year"], m["rating"], m["votes"], label))
            continue
        stats["gap"] += 1
        g = gaps.setdefault(m["id"], {"title": m["title"], "year": m["year"],
                                      "imdb_id": m["id"], "rating": m["rating"],
                                      "votes": m["votes"], "sources": set()})
        g["sources"].add(tag)
    report[key] = stats
    print(f"{key}: parsed {stats['parsed']} | covered {stats['covered']} | real gaps {stats['gap']} | "
          f"non-feature/shorts {stats['nonfeature']} | below 6.0 floor {stats['below_floor']} | "
          f"unresolved noise {stats['unresolved']}", file=sys.stderr)

gap_list = sorted(gaps.values(), key=lambda g: (-g["votes"], g["imdb_id"]))
for g in gap_list:
    g["sources"] = sorted(g["sources"])
    g["tier"] = 2
print(f"\nTOTAL unique real gaps to add: {len(gap_list)}", file=sys.stderr)
print(f"canonical-but-below-6.0 (excluded per owner floor): {len(set(excluded_low))}", file=sys.stderr)

# ── displace lowest-fame popular fill, keep exactly 10,000 ────────────────────
popular = sorted([t for t in titles if t.get("sources") == ["popular"]],
                 key=lambda t: (t["votes"], t["imdb_id"]))
drop_ids = {t["imdb_id"] for t in popular[:len(gap_list)]}
kept = [t for t in titles if t.get("imdb_id") not in drop_ids]
full = kept + gap_list
assert len(full) == 10000, len(full)

canon.update({"version": "2026-08-14.4", "count": len(full), "titles": full})
canon["pillars"]["canon_patch"] = ("Gap-fill from authoritative canons (AFI, Sight & Sound, Academy Award winners, "
                                   "National Film Registry, Palme d'Or/Golden Lion/Golden Bear, BFI 100, box-office): "
                                   "features these lists name that fame ranking missed. No vote floor (>=200 sanity); "
                                   "owner's >=6.0 rating floor enforced. Displaced an equal count of lowest-fame popular fill.")
json.dump(canon, open("/home/claude/canon_10k.json", "w"), ensure_ascii=False, indent=1)

lines = sorted((f"{e['title']} ({e['year']})" for e in full),
               key=lambda s: norm(s.rsplit(" (", 1)[0]) or s.lower())
with open("/home/claude/canon_10k_list.txt", "w", encoding="utf-8") as fh:
    fh.write(f"SIFT CANON - {len(full)} MOVIES\n")
    fh.write("Criterion Collection + cult classics + acclaimed consensus + popular favorites + award/festival/registry canon\n")
    fh.write("Alphabetical (ignoring articles).\n\n")
    fh.write("\n".join(lines) + "\n")

# ── re-verify: final coverage with patched canon ──────────────────────────────
canon_ids = {t["imdb_id"] for t in full if "imdb_id" in t}
canon_ny = set()
for t in full:
    for dy in (-1, 0, 1):
        canon_ny.add((norm(t["title"]), t["year"] + dy))
print("\nFINAL COVERAGE (feature films only, after patch):", file=sys.stderr)
final = {}
for key, (tag, label) in SOURCES.items():
    entries = parse_page(open(f"/tmp/src_{key}.wikitext").read())
    feat = cov = 0
    for (t, y) in entries:
        if (norm(t), y) in canon_ny:
            feat += 1; cov += 1; continue
        m = resolve(t, y)
        if m is None or m["runtime"] is None or not (70 <= m["runtime"] <= 400) or m["votes"] < 200:
            continue
        feat += 1
        if m["id"] in canon_ids: cov += 1
    final[key] = (label, feat, cov)
    print(f"  {label}: {cov}/{feat} ({100*cov/max(1,feat):.1f}%)", file=sys.stderr)

json.dump({"per_source": report, "final": final,
           "gaps_added": gap_list, "excluded_below_floor": sorted(set(excluded_low))},
          open("/home/claude/validation_data.json", "w"), ensure_ascii=False, indent=1, default=list)
print("\nsaved validation_data.json", file=sys.stderr)
