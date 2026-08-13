# Sift — continuous improvement loop log

Newest entries at the bottom. Read the last ~10 before picking work.

---

## Repo map (read this before hunting)

**What it is.** FastAPI backend + React/Vite/TS frontend. Curates a Plex media
library: decides what is junk, what is missing, and — newer — where the disk went.
Deployed on Render against Neon Postgres. Single user, token auth.

**Layout.**

| Path | What lives there |
|---|---|
| `backend/sift/main.py:84` | `create_app`; routers registered at ~199 |
| `backend/sift/api/routes_*.py` | HTTP surface, one module per area |
| `backend/sift/ingest/pipeline.py` | **the scan** — `PHASES` at :56, one `_phase_<name>` each |
| `backend/sift/ingest/normalize.py` | raw API payload → dicts. Pure, no ORM |
| `backend/sift/clients/*.py` | plex, radarr, sonarr, tautulli, tmdb. Async httpx over `BaseClient` |
| `backend/sift/analysis/*.py` | **all ranking/scoring**, pure functions, no ORM in signatures |
| `backend/sift/actions/engine.py` | the *only* execution chokepoint. Deletes are approval-gated, dry-run default |
| `backend/sift/db/models.py` | 20-odd tables. `Movie` keyed on tmdb_id, `Show` on tvdb_id |
| `frontend/src/pages/*.tsx` | Library, Junk, Missing, Storage, Activity, Settings |
| `bench/` | offline benchmarks (added iter 0) |

**Scan flow.** `POST /api/scan` → `services/scanner.launch_scan` → `ScanPipeline.run`
walks `PHASES = (preflight, plex, radarr, sonarr, tautulli, tmdb, finalize, score,
ai)`. Each phase checkpoints into `scan_runs.checkpoints` (free-form JSON) so an
interrupted scan resumes. Network I/O async; DB writes pushed to a thread.

**Ranking lives in `analysis/`.** `scoring.py` (junk score 0-100 → band),
`classify.py` (verdict overlay), `ledger.py` (the reclaim queue: sorts by
`(risk_tier, -bytes_reclaimable)`), `bitrate.py` (bytes/hour baselined on the
library's own median + MAD), `recommend.py` / `tv_recommend.py` (suggestions),
`recognition.py` (public footprint — deliberately NOT used by suitability).

**Three constraints that shape every change.**

1. `create_all` adds **tables**, never **columns**, and the Dockerfile runs uvicorn
   with no Alembic step. New tables deploy free; a new column on a deployed table
   does not.
2. **Round trips dominate on hosted Postgres and are free on SQLite.** Tests run on
   file-backed SQLite, so this entire bug class is invisible to them. 2607.15.1
   exists because of it. Count statements, don't trust the clock.
3. AI never decides correctness. All ranking is deterministic arithmetic.

**Gates (all green as of iter 0).**

```bash
cd /workspace/sift
ruff check backend
./.venv/bin/mypy backend/sift      # strict, 97 files
./.venv/bin/pytest -q              # 401 tests
npm --prefix frontend run build
```

**Benchmarks.**

```bash
./.venv/bin/python bench/bench_score.py    # hot path: statements/film + p50/p95
./.venv/bin/python bench/bench_ledger.py   # ranking: head_value_share + tier order
```

---

### Iter 0 · 2026-08-13 · bootstrap
Mapped the repo above. Confirmed gates green. Built `bench/fixture.py` (seeded
2000-film / 120-show / 5760-episode library with a deliberate long tail and 1-in-40
size outliers), `bench/bench_score.py`, `bench/bench_ledger.py`. Baselines in
`.claude/metrics.jsonl`.

Headline metric choice, and why: the score bench reports **statements per film**,
not milliseconds. The bench runs on SQLite where a round trip is free and ships
against Postgres where it is the only cost — 2607.15.1 was exactly that gap. Wall
clock is reported as a secondary, machine-dependent figure. The ledger bench
reports **head_value_share** (bytes in the top 20 findings / all reclaimable bytes)
because the feature's stated purpose is "biggest wins first", with
`tier_order_violations` as the guardrail that stops a ranking gaming the headline
by putting risky-but-large findings first.

Baseline: `statements_per_film 4.002` (all SELECTs), `p50 2964.6ms` / 2000 films;
ledger `head_value_share 0.0653`, `free_share 0.2174`, `tier_order_violations 0`,
`build_p50 804.2ms`.

**Next (strong lead, found during mapping):** `analysis/junk.py:63-74` issues
**three SELECTs per film** inside `_iter_scores` — `session.get(Movie, id)` at :64
after loading only the ids at :63, `_best_rating(session, id)` at :67, and a
per-film `WatchHistory` query at :74 — plus `movie.score` lazy-loading in
`compute_and_store:119`. That is the 4.002 exactly. Preload all four with chunked
`IN` (500) the way `_persist_plex` does and statements/film should fall toward
~0.01. Prove it with `bench/bench_score.py` before and after; the scored output
must be byte-identical, so pin that too.

### Iter 1 · 2026-08-13 · perf
Batched the scoring reads (`analysis/junk.py`). `_iter_scores` walked films one at
a time, costing four SELECTs each — the film, its ratings, its watch history, and
`movie.score` lazy-loading in `compute_and_store`. Now chunked 500 at a time, and
`Score` rows are preloaded once.
**statements_per_film 4.002 → 0.009** (8004 → 17 total); p50 2964.6 → 196.1ms on
2000 films. Output proved byte-identical: dumped all 2000 scores + preview counts
before and after, `cmp` clean at 1,215,269 bytes.
Two test-quality notes worth remembering: routing the rating-selection pin through
the junk score did **not** work — Bayesian shrinkage pulls a 9-vote rating so far
toward the prior that picking the wrong rating barely moves the score, so the test
passed under mutation. Pinned on `_best_ratings` directly instead. And one
direction of ordering is never enough: with the reliable rating written first,
"keep the last" fails but "keep the first" passes. The test now carries both
directions plus a tie.
Next: `bench_ledger.py` shows `build_p50 734ms` for only 2000 films / 5760
episodes, and `ledger.build` (analysis/ledger.py:109) is the read behind the
Storage page — worth checking whether it has the same per-row shape. Also
`_movie_copy_sizes` at :216 and `_downgrades` at :229 each open their own passes
over `media_files`.
