#!/usr/bin/env python3
"""Summarise what a list rebuild changed, so a refresh PR says something.

A regenerated 25,000-entry JSON file is a 7 MB diff that nobody can read. What a
reviewer actually needs is four numbers and a handful of examples: what came in,
what went out, what moved tier, and whether the metadata still covers what it
covered before.

Written to be run against a checked-out *old* copy and the freshly built *new*
one, and to print Markdown, because its only consumer is a pull request body.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, dict[str, Any]]:
    """Entries keyed by IMDb id, or by title+year for the few without one."""
    data = json.loads(path.read_text())
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("titles", []):
        key = row.get("imdb_id") or f"{row.get('title')}|{row.get('year')}"
        out[str(key)] = row
    return out


def coverage(entries: dict[str, dict[str, Any]], field: str) -> float:
    if not entries:
        return 0.0
    return sum(1 for e in entries.values() if e.get(field)) / len(entries)


def describe(row: dict[str, Any]) -> str:
    year = row.get("year")
    return f"{row.get('title')}" + (f" ({year})" if year else "")


def report(old_path: Path, new_path: Path, label: str) -> str:
    old, new = load(old_path), load(new_path)
    added = [new[k] for k in new.keys() - old.keys()]
    removed = [old[k] for k in old.keys() - new.keys()]
    retiered = [
        (old[k], new[k])
        for k in old.keys() & new.keys()
        if old[k].get("tier") != new[k].get("tier")
    ]

    lines = [f"### {label}", ""]
    lines.append("| | before | after |")
    lines.append("|---|---:|---:|")
    lines.append(f"| entries | {len(old):,} | {len(new):,} |")
    for field in ("genres", "runtime", "directors"):
        before, after = coverage(old, field), coverage(new, field)
        if before or after:
            lines.append(f"| with `{field}` | {before:.0%} | {after:.0%} |")
    lines.append("")
    lines.append(f"**{len(added):,} added · {len(removed):,} removed · "
                 f"{len(retiered):,} changed tier**")

    # Sorted by fame so the examples are ones a reviewer might recognise, rather
    # than whichever entries happened to hash first.
    if added:
        lines += ["", "New, most-voted first:", ""]
        for row in sorted(added, key=lambda r: -(r.get("votes") or 0))[:8]:
            lines.append(f"- {describe(row)} — tier {row.get('tier')}, "
                         f"{(row.get('votes') or 0):,} votes")
    if removed:
        lines += ["", "Dropped, most-voted first — **worth a look, since anything "
                  "here was on the list last time**:", ""]
        for row in sorted(removed, key=lambda r: -(r.get("votes") or 0))[:8]:
            lines.append(f"- {describe(row)} — was tier {row.get('tier')}, "
                         f"{(row.get('votes') or 0):,} votes")
    if retiered:
        lines += ["", "Moved tier:", ""]
        for was, now in sorted(retiered, key=lambda p: -(p[1].get("votes") or 0))[:8]:
            lines.append(f"- {describe(now)} — {was.get('tier')} → {now.get('tier')}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--label", default="List")
    args = parser.parse_args()
    print(report(args.old, args.new, args.label))


if __name__ == "__main__":
    main()
