#!/usr/bin/env python3
"""Fetch every parseable authoritative film canon and measure the 10k list's coverage."""
import json, os, re, sys, time, unicodedata, urllib.parse, urllib.request

UA = {"User-Agent": "SiftCanonBuilder/1.0 (jasonsimmonds13@gmail.com) personal library research"}
YEAR_LO, YEAR_HI = 1890, 2026
LINK = re.compile(r"''+\[\[([^\]|]+)(?:\|([^\]]+))?\]\]''+")
SORTNAME = re.compile(r"\{\{sortname\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}")

def fetch(title, cache):
    if os.path.exists(cache):
        return open(cache).read()
    params = {"action": "parse", "page": title, "prop": "wikitext", "format": "json"}
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
            if "error" in r:
                return None
            wt = r["parse"]["wikitext"]["*"]
            open(cache, "w").write(wt)
            time.sleep(5)
            return wt
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
            elif e.code == 404:
                return None
            else:
                raise
    return None

def clean(target, display):
    t = (display or target).strip()
    return re.sub(r"\s*\((?:\d{4}\s+)?film\)$", "", t).strip()

def title_from(text):
    m = LINK.search(text)
    if m:
        return clean(m.group(1), m.group(2))
    sn = SORTNAME.search(text)
    if sn:
        return f"{sn.group(1).strip()} {sn.group(2).strip()}"
    return None

def years_in(text):
    return [int(y) for y in re.findall(r"\b(1[89]\d\d|20[0-2]\d)\b", text)]

def parse_page(wt):
    """Union of three row shapes: inline table rows, cell-per-line blocks, bullets."""
    out = set()
    # inline rows and bullets: title + year on one line
    for line in wt.splitlines():
        s = line.strip()
        if not (s.startswith("|") or s.startswith("*") or s.startswith("#")):
            continue
        t = title_from(s)
        if not t:
            continue
        ys = years_in(s)
        if ys:
            out.add((t, ys[0]))
    # cell-per-line blocks
    for block in re.split(r"^\|-.*$", wt, flags=re.M):
        t = title_from(block)
        if not t:
            continue
        for line in block.splitlines():
            m = re.match(r"^\|\s*(1[89]\d\d|20[0-2]\d)\s*(?:\{\{|$|\|)", line.strip())
            if m:
                out.add((t, int(m.group(1))))
                break
    return out

SOURCES = [
    ("afi_1998",   "AFI's 100 Years...100 Movies"),
    ("afi_2007",   "AFI's 100 Years...100 Movies (10th Anniversary Edition)"),
    ("sight_sound","The Sight and Sound Greatest Films of All Time 2022"),
    ("oscar_wins", "List of Academy Award–winning films"),
    ("box_office", "List of highest-grossing films"),
    ("film_registry", "National Film Registry"),
    ("palme_dor",  "Palme d'Or"),
    ("golden_lion","Golden Lion"),
    ("golden_bear","Golden Bear"),
    ("ebert_great","The Great Movies"),
    ("bfi_top100", "BFI Top 100 British films"),
    ("time_100",   "All-Time 100"),
    ("must_1001",  "1001 Movies You Must See Before You Die"),
]

def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = re.sub(r"^(the|a|an|le|la|les|el|il|der|die|das)\s+", "", t)
    return re.sub(r"[^a-z0-9]", "", t)

canon = json.load(open("/home/claude/canon_10k.json"))
have = set()
for t in canon["titles"]:
    n = norm(t["title"])
    for dy in (-1, 0, 1):
        have.add((n, t["year"] + dy))

results = {}
for key, page in SOURCES:
    wt = fetch(page, f"/tmp/src_{key}.wikitext")
    if not wt:
        print(f"{key}: PAGE NOT FOUND", file=sys.stderr)
        continue
    entries = {(t, y) for (t, y) in parse_page(wt) if YEAR_LO <= y <= YEAR_HI}
    missing = sorted((t, y) for (t, y) in entries if (norm(t), y) not in have)
    results[key] = {"page": page, "parsed": len(entries),
                    "matched": len(entries) - len(missing), "missing": missing}
    pct = 100 * results[key]["matched"] / max(1, len(entries))
    print(f"{key}: parsed {len(entries)}, matched {results[key]['matched']} ({pct:.0f}%), missing {len(missing)}", file=sys.stderr)

json.dump(results, open("/home/claude/sweep_results.json", "w"), ensure_ascii=False, indent=1)
print("saved sweep_results.json", file=sys.stderr)
