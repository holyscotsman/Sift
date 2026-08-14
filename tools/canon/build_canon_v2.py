#!/usr/bin/env python3
"""Three-pillar 5000-title canon:
   1. Criterion Collection membership (Wikipedia: List of films in the Criterion Collection)
   2. Cult classics (Wikipedia: List of cult films, 27 subpages)
   3. Theatrical-consensus fill (IMDb datasets, Bayesian WR ranking)
Deterministic composition; pillar membership recorded per entry."""
import csv, gzip, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from collections import defaultdict

UA = {"User-Agent": "SiftCanonBuilder/1.0 (jasonsimmonds13@gmail.com) personal library research"}
YEAR_LO, YEAR_HI = 1890, 2026

def fetch_wikitext(title, cache):
    if os.path.exists(cache):
        return open(cache).read()
    params = {"action": "parse", "page": title, "prop": "wikitext", "format": "json"}
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
            wt = r["parse"]["wikitext"]["*"]
            open(cache, "w").write(wt)
            time.sleep(5)
            return wt
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
            else:
                raise
    raise RuntimeError(f"could not fetch {title}")

LINK = re.compile(r"''+\[\[([^\]|]+)(?:\|([^\]]+))?\]\]''+")
SORTNAME = re.compile(r"\{\{sortname\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}")
YEARCELL = re.compile(r"^\|\s*(\d{4})\s*(?:\{\{|$)")
NUMCELL = re.compile(r"^\|\s*(?:rowspan=\"\d+\"\s*\|)?\s*(\d{1,4})\s*(?:\{\{|$)")

def clean_title(target, display):
    t = display or target
    t = re.sub(r"\s*\((?:\d{4}\s+)?film\)$", "", t).strip()
    return t

def parse_inline_rows(wt):
    """Yield (title, year) from single-line rows: | ''[[Title]]'' || 1973 || ..."""
    for line in wt.splitlines():
        if not line.startswith("|") or "||" not in line:
            continue
        cells = line.split("||")
        m = LINK.search(cells[0])
        if m:
            title = clean_title(m.group(1), m.group(2))
        else:
            sn = SORTNAME.search(cells[0])
            if not sn:
                continue
            title = f"{sn.group(1).strip()} {sn.group(2).strip()}"
        year = None
        for cell in cells[1:3]:
            ym = re.search(r"\b(\d{4})\b", cell)
            if ym and YEAR_LO <= int(ym.group(1)) <= YEAR_HI:
                year = int(ym.group(1))
                break
        if year:
            yield title, year

def parse_blocks(wt):
    """Yield (title, year, spine_or_None) per table row block."""
    for block in re.split(r"^\|-.*$", wt, flags=re.M):
        m = LINK.search(block)
        if not m:
            continue
        title = clean_title(m.group(1), m.group(2))
        year = spine = None
        for line in block.splitlines():
            ym = YEARCELL.match(line.strip())
            if ym:
                v = int(ym.group(1))
                if YEAR_LO <= v <= YEAR_HI and year is None:
                    year = v
                    continue
            nm = NUMCELL.match(line.strip())
            if nm and spine is None:
                v = int(nm.group(1))
                if v < YEAR_LO:
                    spine = v
        if title and year:
            yield title, year, spine

def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = re.sub(r"^(the|a|an)\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)

# ── pillar 1: Criterion ───────────────────────────────────────────────────────
crit_wt = fetch_wikitext("List of films in the Criterion Collection", "/tmp/criterion.wikitext")
criterion = {}
for title, year, spine in parse_blocks(crit_wt):
    criterion.setdefault((norm(title), year), (title, year, spine))
print(f"criterion entries parsed: {len(criterion)}", file=sys.stderr)

# ── pillar 2: cult films ──────────────────────────────────────────────────────
pages = ["0–9"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
cult = {}
for p in pages:
    wt = fetch_wikitext(f"List of cult films: {p}", f"/tmp/cult_{p}.wikitext")
    n0 = len(cult)
    for title, year in parse_inline_rows(wt):
        cult.setdefault((norm(title), year), (title, year))
    print(f"  cult {p}: +{len(cult)-n0}", file=sys.stderr)
print(f"cult entries parsed: {len(cult)}", file=sys.stderr)

# ── IMDb index (ALL movie-type rows — no vote floor for pillar matching) ──────
ratings = {}
with gzip.open("/tmp/ratings.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t"); next(rd)
    for tconst, rating, votes in rd:
        ratings[tconst] = (float(rating), int(votes))

idx = defaultdict(list)           # (norm_title, year) -> [tconst]
qualified = []                    # votes >= 5000 pool for consensus fill
with gzip.open("/tmp/basics.tsv.gz", "rt", encoding="utf-8") as f:
    rd = csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE); next(rd)
    for row in rd:
        try:
            tconst, ttype, primary, original, adult, y, _, rt, genres = row
        except ValueError:
            continue
        if ttype != "movie" or adult == "1" or not y.isdigit():
            continue
        y = int(y)
        if not (YEAR_LO <= y <= YEAR_HI):
            continue
        idx[(norm(primary), y)].append(tconst)
        if norm(original) != norm(primary):
            idx[(norm(original), y)].append(tconst)
        rv = ratings.get(tconst)
        if rv and rv[1] >= 5000 and rt.isdigit() and 70 <= int(rt) <= 400:
            qualified.append({"imdb_id": tconst, "title": primary, "year": y,
                              "rating": rv[0], "votes": rv[1]})
print(f"imdb movie index keys: {len(idx)}; consensus pool: {len(qualified)}", file=sys.stderr)

C = sum(f["rating"] for f in qualified) / len(qualified)
M = 25000
def wr(rating, votes): return round(votes / (votes + M) * rating + M / (votes + M) * C, 4)
for f in qualified:
    f["wr"] = wr(f["rating"], f["votes"])
qualified.sort(key=lambda f: (-f["wr"], -f["votes"], f["imdb_id"]))

def match(nt, year):
    """Best IMDb id for a normalized title near a year: most-voted candidate."""
    cands = []
    for dy in (0, 1, -1):
        cands += idx.get((nt, year + dy), [])
    if not cands:
        return None
    return max(set(cands), key=lambda t: (ratings.get(t, (0, 0))[1], t))

# ── compose ───────────────────────────────────────────────────────────────────
entries = {}   # key: imdb_id if matched else (norm,year)
def add(title, year, sources, spine=None):
    nt = norm(title)
    tid = match(nt, year)
    key = tid or (nt, year)
    if key in entries:
        e = entries[key]
        e["sources"] = sorted(set(e["sources"]) | set(sources))
        if spine and "spine" not in e:
            e["spine"] = spine
        return
    e = {"title": title, "year": year, "sources": sorted(sources)}
    if tid:
        e["imdb_id"] = tid
        r = ratings.get(tid)
        if r:
            e["rating"], e["votes"] = r
    if spine:
        e["spine"] = spine
    entries[key] = e

for (nt, y), (title, year, spine) in criterion.items():
    add(title, year, ["criterion"], spine)
for (nt, y), (title, year) in cult.items():
    add(title, year, ["cult"])
pillar_count = len(entries)
crit_matched = sum(1 for e in entries.values() if "criterion" in e["sources"] and "imdb_id" in e)
cult_matched = sum(1 for e in entries.values() if "cult" in e["sources"] and "imdb_id" in e)
both = sum(1 for e in entries.values() if {"criterion", "cult"} <= set(e["sources"]))
print(f"pillar union: {pillar_count} (criterion matched {crit_matched}, cult matched {cult_matched}, both-lists {both})", file=sys.stderr)

# merge residual duplicates where one copy matched an imdb_id and another didn't
by_ny = {}
for e in entries.values():
    key = (norm(e["title"]), e["year"])
    if key in by_ny:
        keep, drop = (e, by_ny[key]) if "imdb_id" in e else (by_ny[key], e)
        keep["sources"] = sorted(set(keep["sources"]) | set(drop["sources"]))
        if "spine" in drop:
            keep.setdefault("spine", drop["spine"])
        by_ny[key] = keep
    else:
        by_ny[key] = e
canon = list(by_ny.values())

TARGET = 5000
taken_ids = {e["imdb_id"] for e in canon if "imdb_id" in e}
taken_ny = set(by_ny)
fill_rank = 0
for f in qualified:
    if len(canon) >= TARGET:
        break
    if f["imdb_id"] in taken_ids or (norm(f["title"]), f["year"]) in taken_ny:
        continue
    fill_rank += 1
    tier = 1 if fill_rank <= 500 else 2 if fill_rank <= 1500 else 3 if fill_rank <= 3000 else 4
    canon.append({"title": f["title"], "year": f["year"], "imdb_id": f["imdb_id"],
                  "rating": f["rating"], "votes": f["votes"],
                  "sources": ["imdb_wr"], "tier": tier})
canon.sort(key=lambda e: (-wr(e["rating"], e["votes"]) if "votes" in e else 0,
                          -e.get("votes", 0), norm(e["title"]), e["year"]))
canon = canon[:TARGET] if len(canon) > TARGET else canon

out = {
    "name": "canon_expanded",
    "version": "2026-08-14.2",
    "pillars": {
        "criterion": "List of films in the Criterion Collection (Wikipedia, CC BY-SA), full membership. Entries carry spine where parsed.",
        "cult": "List of cult films A-Z (Wikipedia, CC BY-SA), full membership.",
        "imdb_wr": f"Theatrical-consensus fill from official IMDb datasets: features >=5000 votes ranked by WR (m={M}, C={C:.3f}), tiered 1-4 by fill rank.",
    },
    "weighting": "criterion or cult membership = curated floor (tier-1 equivalent, per 2607.13.0). imdb_wr entries weight by tier: 1.0/0.75/0.5/0.3.",
    "resolution": "Entries with imdb_id resolve via TMDB /find/{imdb_id} (exact). Entries without imdb_id resolve by title+year search (repo convention). Resolution lazily budgeted per scan; never 5000 lookups in one scan.",
    "count": len(canon),
    "titles": canon,
}
with open("/home/claude/canon_expanded.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(f"wrote canon_expanded.json with {len(canon)} titles "
      f"({pillar_count} pillar + {len(canon)-pillar_count} consensus fill)", file=sys.stderr)
