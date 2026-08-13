"""Latency benchmark for the scan's hot path: junk scoring.

**Why statements, not just milliseconds.** The benchmark runs on local SQLite,
where a round trip costs nothing, and ships against hosted Postgres, where a
round trip is the only thing that costs. Release 2607.15.1 exists because that
gap hid a per-row ``session.merge`` until it reached production. So the headline
metric here is **database statements per film** — the number that actually
predicts hosted behaviour — with wall-clock p50/p95 reported alongside as the
secondary, machine-dependent figure.

A change that lowers milliseconds while leaving statements flat has not fixed the
thing that makes a real scan feel hung.

    python bench/bench_score.py            # JSON to stdout
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import event  # noqa: E402

from fixture import build_library, summarize  # noqa: E402
from sift.analysis import junk  # noqa: E402
from sift.config import JunkThresholds  # noqa: E402

FILMS = 2000
REPEATS = 5


def _count_statements(factory, fn):
    """(result, statements) for one call, counting every cursor execution."""
    engine = factory.kw["bind"]
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        seen.append(statement.lstrip().split()[0].upper())

    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return result, seen


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        factory = build_library(Path(tmp) / "bench.db", films=FILMS, shows=0)
        shape = summarize(factory)
        thr = JunkThresholds()

        # One warm pass first: the first run creates every Score row, and an
        # insert-heavy pass is not the steady state a scheduled rescan lives in.
        junk.compute_and_store(factory, thr)

        timings: list[float] = []
        statements: list[str] = []
        for _ in range(REPEATS):
            start = time.perf_counter()
            (written, statements) = _count_statements(
                factory, lambda: junk.compute_and_store(factory, thr)
            )
            timings.append((time.perf_counter() - start) * 1000.0)

        quantiles = sorted(timings)
        report = {
            "bench": "score",
            "films": shape["films"],
            "written": written,
            "statements_total": len(statements),
            "statements_per_film": round(len(statements) / max(shape["films"], 1), 3),
            "selects_per_film": round(
                statements.count("SELECT") / max(shape["films"], 1), 3
            ),
            "p50_ms": round(statistics.median(quantiles), 1),
            "p95_ms": round(quantiles[min(len(quantiles) - 1, int(len(quantiles) * 0.95))], 1),
        }
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
