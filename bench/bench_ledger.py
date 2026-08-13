"""Quality benchmark for the reclaim ledger — Sift's actual ranking problem.

**Why this metric.** Sift has no learned model to score, so precision/recall
against labels would be theatre. What it does have is a ranked queue, and the
request it was built for was explicit: *biggest disk wins first*, safest first.
Those two are the ranking, so those two are what get measured.

Headline: **``head_value_share``** — the fraction of all reclaimable bytes that
sits in the first 20 findings. A ranking that front-loads the wins scores high; a
ranking that scatters a few large findings through a long tail of small ones
scores low, and a person working the queue top-down gets less back per decision.

Guardrails reported alongside, because a ranking can raise the headline by
cheating:

* ``tier_order_violations`` — a judgement-tier finding ranked above a zero-loss
  one. Sorting purely by size would maximise the headline and be *wrong*: the
  whole design is that free bytes come before bytes that cost quality.
* ``free_share`` — how much of the total needs no taste judgement at all.
* ``plan_*`` — what the target-driven planner does with a fixed 500 GB ask.

    python bench/bench_ledger.py
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

from fixture import build_library, summarize  # noqa: E402
from sift.analysis import ledger  # noqa: E402

HEAD = 20
TARGET_BYTES = 500 * 1_000_000_000
REPEATS = 3


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        factory = build_library(Path(tmp) / "bench.db")
        shape = summarize(factory)

        timings: list[float] = []
        for _ in range(REPEATS):
            start = time.perf_counter()
            with factory() as session:
                book = ledger.build(session)
            timings.append((time.perf_counter() - start) * 1000.0)

        findings = book.findings
        head = findings[:HEAD]
        total = book.total_reclaimable or 1

        # A later finding may never sit in a safer tier than an earlier one.
        violations = 0
        worst = -1
        for finding in findings:
            if finding.risk_tier < worst:
                violations += 1
            worst = max(worst, finding.risk_tier)

        outcome = ledger.plan(book, TARGET_BYTES)
        kinds: dict[str, int] = {}
        for finding in findings:
            kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
        report = {
            "bench": "ledger",
            "library": shape,
            "findings": len(findings),
            "total_reclaimable_gb": round(book.total_reclaimable / 1e9, 1),
            "head_value_share": round(
                sum(f.bytes_reclaimable for f in head) / total, 4
            ),
            "free_share": round(book.by_tier.get(ledger.TIER_FREE, 0) / total, 4),
            "tier_order_violations": violations,
            # Reported so a fixture that stops exercising a finding kind shows up
            # as a missing key rather than as a silently narrower benchmark.
            "kinds": dict(sorted(kinds.items())),
            "plan_reached": outcome.reached,
            "plan_steps": len(outcome.steps),
            "plan_highest_tier": outcome.highest_tier,
            "build_p50_ms": round(statistics.median(timings), 1),
        }
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
