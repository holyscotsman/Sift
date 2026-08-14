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

### Iter 2 · 2026-08-13 · perf
`tv_duplicates.find` hydrated `MediaFile+Episode+Season+Show` for **every** episode
file, then kept the few percent with more than one file. Now asks the database
which episode ids have >1 file (`GROUP BY … HAVING COUNT > 1`) and reads only
those, chunked 500.
**417.7 → 46.5ms** (9x); `ledger.build` 758.6 → 597.9ms. Ledger output identical
(58,269-byte canonical dump, `cmp` clean).
Important framing correction for future iterations: the ledger is **CPU-bound, not
round-trip bound** — the whole build is only 9 statements. Statement counting is
the right metric for the *scan*; for the Storage page read it is ORM hydration
volume that matters. Profile with /tmp/profile_ledger.py style timing, not
statement counts.
Next: same shape in `tv_size.seasons` (188ms) and `ledger._downgrades` (170ms) —
both re-run the identical 4-table join over every episode file, and `_downgrades`
only ever needs seasons whose show could plausibly be downgraded. `outliers.find`
is 108ms. Those three are now 78% of the build.

### Iter 3 · 2026-08-13 · perf
`tv_size._load` and `ledger._downgrades` each ran the same four-table join and
hydrated a full `MediaFile` ORM entity per row to read four attributes off it.
Replaced with one shared column-select loader (`tv_size.load_seasons` →
`SeasonGroup`/`SeasonFile` NamedTuples) plus `load_shows` (a few hundred rows, read
whole instead of joined onto every file).
**tv_size.seasons 188.7 → 26.5ms, _downgrades 170.6 → 46.5ms, ledger.build 597.9 →
208.5ms** (cumulative from iter 0: 758.6 → 208.5, 3.6x). Ledger dump identical.
**Caution recorded:** my equivalence dump for `tv_size.inconsistencies` returned
`[]` — 3 bytes — so it proved nothing. The fixture generates no inconsistent
seasons at all. Fell back to the three existing behavioural tests, which do cover
it. This is a real gap in the benchmark fixture.
Next: (a) `bench/fixture.py` generates no inconsistent seasons and no
truncated/bad-rip films with wrong *duration* — so `inconsistencies` and part of
`outliers` are unexercised by the bench; fixing it means re-baselining every
metric, so do it as its own iteration. (b) `outliers.find` is now the largest
single cost at 103ms. (c) `load_seasons` is still executed once per caller —
hoisting it to a single per-request load would remove another join from `build`.

### Iter 4 · 2026-08-13 · measurement
Fixed the fixture gap iter 3 exposed. Added inconsistent seasons (odd-resolution +
off-rate episodes in every 5th season), truncated films (duration stops short of
runtime), and **legitimate short films that must not be flagged** — the case a
fixture of only-broken-things can never catch.
Outlier kinds {oversized, bad_rip} → {oversized, bad_rip, truncated}; inconsistent
seasons 0 → 96; all three risk tiers now populated (132/50/63). `bench_ledger.py`
now prints the kind breakdown so a future fixture that stops exercising a kind
shows as a missing key.
**Every metric before iter 4 was measured on the poorer fixture and is NOT
comparable.** New baseline: build_p50 242.1ms, head_value_share 0.0646,
statements_per_film 0.009.
Next: `outliers.find` (103ms pre-fixture-change) is now the largest single cost in
`build`. Also `load_seasons` still runs once per caller inside `build` — hoisting
it to a single load would drop one join.

### Iter 5 · 2026-08-13 · perf
`outliers.find` selected `MediaFile` and `Movie` entities to read six attributes
off each. Replaced with a `FilmFile` NamedTuple column select; `_small_file_finding`
now takes one row instead of a movie and a file.
**outliers.find 106.2 → 56.6ms; build_p50 242.1 → 167.6ms.** Ledger dump identical
(61,358 bytes). Interesting side effect: `_downgrades` also fell 51.4 → 24.8ms
without being touched — the ORM identity map was being populated by outliers and
paying off elsewhere, which means per-component timings in this profile are not
fully independent. Treat `build (whole)` as the trustworthy number.
Next: `load_baselines` (26.5ms) reads every media file to compute medians and is
called twice per `build` — once directly, once inside `outliers.find`. Hoisting it
is a small, safe win. `tv_duplicates.find` at 40.2ms is now second-largest.

### Iter 6 · 2026-08-13 · perf
`ledger.build` measured the bitrate baselines twice (once directly, once inside
`outliers.find`) and ran the season join twice (`tv_size.seasons` and
`_downgrades`). Now loaded once in `build` and passed down; both callees keep an
optional parameter so standalone use is unchanged.
**build_p50 167.6 → 131.9ms, statements 12 → 9.** Ledger dump identical.
Cumulative across iters 2/3/5/6 on the same fixture: 758.6 → 131.9ms is not a fair
claim (fixture changed at iter 4); on the *current* fixture the honest span is
242.1 → 131.9ms, 1.8x.
Next: `load_baselines` reads every media file (26ms) — it is a pure aggregation
(median + MAD per resolution/codec bucket) and could be pushed into SQL, but the
median is the hard part and MAD needs a second pass, so this may not be worth it.
`tv_duplicates.find` at ~40ms is the largest remaining. Beyond the ledger, nothing
in `analysis/` has been examined for correctness yet — only for speed.

### Iter 7 · 2026-08-13 · correctness
**Real bug.** `max(set(values), key=values.count)` in three places
(`ledger.py:252`, `ledger._dominant_codec`, `tv_size._dominant`) reads as "the most
common value" and is — except on a tie, where it returns whichever tied value
`set` iteration reaches first. For strings that order comes from Python's
per-process hash seed, so an evenly split season resolved to either resolution,
**differing between runs of identical code over an identical library**. It decides
whether an irreversible quality downgrade is proposed and how big its saving looks.
Replaced with `tv_size.dominant(values, rank=…)`: counts in insertion order, ties
broken toward the *lowest* rank — the lower resolution, the less efficient codec.
Both make a proposed downgrade look smaller, which is the right way to be wrong
about a destructive suggestion.
**Proof required two goes.** The first end-to-end determinism check passed on both
the old and new code, because the fixture contained **zero** tied seasons — the
check was vacuous. Added parity-split seasons to the fixture (56 ties of 480
seasons; the duplicate copy had to be suppressed on those shows or it tipped the
split by one file). With ties present the old code emits **two distinct ledgers
across 8 hash seeds**; the new code emits one.
Test carries its own negative control: a subprocess check that the *original*
expression really does vary across seeds, so a passing determinism test can't be
passing for the wrong reason.
Fixture changed again → build_p50 re-baselined to 129.9ms.
Next: same `max(set(...), key=list.count)` idiom may exist elsewhere — grep found
only these three, but `sorted()`/`max()` over dict iteration is worth a sweep.
`analysis/recommend.py` and `tv_recommend.py` have had no correctness pass at all.

### Iter 8 · 2026-08-13 · correctness
**Second real bug, same family.** Every ranking sort in `analysis/` had a
*non-total* key, and none of the queries feeding them specify `ORDER BY`. SQLite
returns rowid order — which is why no existing test could see this — and Postgres
promises nothing for an unordered SELECT. Two equal-scoring findings therefore kept
whatever order the rows arrived in, and the reclaim page shows only the first 500,
so it changes *which* findings a person sees.
Reproduced by handing the loaders their rows reversed: the ledger produced two
different digests (`4cae14b9` vs `ebffe5ad`). Added identity tails to eight sorts
across 7 files (ledger, outliers, tv_duplicates, tv_size ×2, tv_recommend,
collections, recommend ×2). Now one digest.
**Three of my first four mutation checks were false negatives — worth reading:**
- ledger tie-break: test passed under mutation because the fixture produced no
  `quality_downgrade` findings, and tier 2 is the *only* tier whose producer
  (`_downgrades`) does not sort its own output. Added three tied cartoons.
- tv_duplicates: test compared two runs *in the same process*, and `hash(str)` is
  stable within a process — so an arbitrary key passed. Now asserts the expected
  order explicitly, not merely self-consistency.
- outliers: adding the cartoons moved the library's own 1080p median so the 40 GB
  films stopped being outliers at all. Gave that test its own films-only fixture.
Next: `services/` and `api/` have had no correctness pass. `routes_storage.py`
`/act` validates paths against `media_files` — worth checking it cannot be walked
past. Also the long-standing `base_url` SSRF hole (any authenticated caller can
repoint a service at a host they control and have Sift send it credentials) is
still open and is the most serious known issue in the repo.

### Iter 9 · 2026-08-13 · security
Closed the direct half of the long-standing `base_url` SSRF. Sift stores an API key
per service and sends it to whatever base URL is configured; every major cloud
serves instance credentials from a link-local address with no auth, and Sift runs on
Render. So "test my connection" could read the deploy's own keys, with the answer
returned through the health endpoint.
Guard added in `BaseClient.__init__` — the one place every client, health probe,
connection test and scan must pass through. Blocks link-local literals (including
IPv4-mapped IPv6, `::ffff:169.254.169.254`), the known metadata hostnames, and any
scheme that is not http/https. **Private ranges are deliberately still allowed** —
Plex and Radarr live on a home LAN, so blocking 192.168.x.x would break normal use
to defend against nothing. That is the negative control, and it is the half that
matters: an over-broad guard passes every attack test and makes the product
unusable.
**Known residual, stated in the docstring:** a *hostname* that resolves to a
link-local address is not caught. Catching it needs a resolving transport hook plus
a DNS lookup per client construction, and still loses to rebinding.
Next (needs an owner decision, not an autonomous one): changing a service's
`base_url` currently keeps the stored secret, so a repointed service still gets the
credential. Clearing the secret on URL change is the standard protection but costs
real UX — fixing a typo in a URL would force re-entering the API key. Worth asking
before doing.

### Iter 10 · 2026-08-13 · safety
`/api/storage/act` validated that every path exists in `media_files`, and its
docstring claimed this "stops this being a way to have the agent delete arbitrary
things". It stopped arbitrary *paths*, not arbitrary *deletions*: a request naming
every copy of an episode passed, because both copies exist. "Only the surplus goes"
was a property of how findings were computed, not of what the endpoint accepted —
so a stale page, a repeated call or a client bug had nothing standing in its way.
Added `_would_strand`: counts, per episode and per film, what is being asked for
against everything on record, and refuses if any title would be left with zero
files. Removing 2 of 3 copies is fine; removing 3 of 3 is not. Docstring corrected
to say what it actually does.
Negative control matters as much as the guard: refusing *any* episode delete would
pass the attack test and make the entire duplicate report useless, since removing
one of two files is its whole purpose.
Next: `tools/sift-agent.py` is the thing with filesystem access — it has had no
review in this loop. Also `actions/engine.py` approval guard is pinned by
`test_actions_safety.py` but the FileJob claim path (`routes_agent.py`) is newer
and may not be covered as thoroughly.

### Iter 11 · 2026-08-13 · correctness (data loss)
`tools/sift-agent.py` had **no tests at all** and is the only component that
touches files. Its safety story is that approved deletes are *moved* to
`.sift-trash` rather than unlinked — but it used `shutil.move` onto
`trash/<basename>`, and `shutil.move` replaces an existing destination silently.
Two files with one basename is not exotic here: `_transcode` moves the original
into the trash and writes the new encode out **under the source's own name**, so
any later delete of that encode targets the identical trash path and would erase
the original it was there to protect.
`_free_name()` now picks `<stem>.1<suffix>` and so on, and refuses rather than
overwrites after a thousand collisions. Negative control pins that an
uncollided name is left exactly as it was — uniquifying unconditionally would make
every restore a guessing game.
Added the first tests for the agent (3), including that a dry run moves nothing.
Next: `_transcode`'s `final = path.with_suffix(output.suffix)` is wrong for a
source with no extension (`/a/movie` → writes `/a/movie.mkv`, leaving the original
name unused). Minor. More interesting: the agent retries nothing and a job that
fails mid-encode leaves `.sift-h265.mkv` behind on some paths.

### Iter 12 · 2026-08-13 · correctness (user-visible)
`routes_agent.report` branched on `if body.ok and job.kind == "transcode"`, and the
success branch demanded an output size and duration. Only a transcode has those —
a delete produces no new file — so **every completed delete fell through to the
failure branch**: job marked failed, action marked FAILED, and an invented error
("the agent reported a failure") attached. The reclaim feature emits nothing but
delete jobs, so this was all of them, and the Activity log would have shown a
library of successful deletions as a wall of failures.
Fixed by branching on `body.ok` first and applying the numbers requirement only to
transcodes. Two negative controls: a failed delete must still record as failed, and
a transcode must still be refused without its numbers — a truncated encode looks
exactly like a success and swapping it in destroys the film.
Next: nothing in `frontend/` has been examined. Also `_transcode`'s `final =
path.with_suffix(output.suffix)` misnames the output when the source has no
extension.

### Iter 13 · 2026-08-13 · correctness (data loss)
Logged as a cosmetic naming issue; it is the iter-11 family again. `_transcode`
computes `final = path.with_suffix(output.suffix)`, so re-encoding `film.avi`
writes `film.mkv` — and `shutil.move` onto an existing `film.mkv` destroys it. A
second copy of one film in one folder is not a corner case: it is exactly what the
duplicate report surfaces, so the bystander is a file nobody approved for
deletion.
Destination is now checked **before** the original is moved to trash, so refusing
leaves the library untouched. `samefile` rather than a path comparison, so the
ordinary same-extension re-encode (`film.mkv` → `film.mkv`, destination *is* the
source) still works — that is the negative control, and refusing on
`final.exists()` alone would block every one of them.
Added the agent's first transcode tests with a fake HandBrake.
Next: the agent still has no test for `_verify` (duration tolerance, min output
fraction) — the guard that stops a truncated encode being swapped in. Nothing in
`frontend/` examined yet.

### Iter 14 · 2026-08-13 · correctness (data loss)
`_verify` — described in its own docstring as "the load-bearing part of the whole
agent" — had a hole and no tests. The duration comparison ran only `if
source_seconds and output_seconds`, with an `elif output_seconds is None` refusal.
So when the **source** would not probe and the output would, both branches fell
through and the function returned `None`, meaning *passed*. The only remaining
floor is the 5% size check, which an encode containing half the episode clears
easily — and a truncated file that plays is indistinguishable from a good one to
everything downstream.
Now refuses unless both durations are known. Behaviour is unchanged where ffprobe
is missing entirely (that already refused). Truthiness replaced with `is None`, so
a 0.0-second probe is a fact rather than a skip.
Four tests added, three mutations verified including the over-broad one (refusing
whenever a duration is missing must not become refusing everything, or nothing
ever swaps).
Next: the agent's `claim`/`report` HTTP paths are still untested — `tick()` swallows
every exception, so a persistently failing report would spin silently. Nothing in
`frontend/` examined yet.

### Iter 15 · 2026-08-13 · correctness (audit integrity)
The agent's `report()` swallowed every network error with the comment "losing the
report only means Sift shows the job as still claimed until the next scan
reconciles it". **Nothing reconciles it** — grepped the whole backend; `claim`
only ever selects `status == "queued"`, and no code path moves a stale `claimed`
job anywhere. So a single dropped connection left the file moved, the job claimed
for ever, and an approved action recorded as never executed for work that did
happen. The one safe part is that the job is never handed out again, so the work
is not repeated.
Now retries 4× with exponential backoff, `sleep` injected for testability. A 4xx
is deliberately **not** retried — a bad token or unknown job will not become true
by asking again. Comment rewritten to describe what actually happens.
Four tests, two mutations verified (no-retry; retry-4xx-too).
Next: **server-side reconciliation of stale `claimed` jobs still does not exist**
and is the real fix — a job claimed longer than some window should return to
`queued` or be surfaced. Needs a timeout policy, so it is a larger slice. Also
`frontend/` remains completely unexamined.

### Iter 16 · 2026-08-13 · security
`services/auth.py` is otherwise solid — pbkdf2 240k rounds, `compare_digest`,
signed tokens with `exp`, per-account sliding-window rate limiting keyed by
username rather than IP (correct behind a proxy). One gap: `change_password`
**deliberately kept the signing secret**, documented as "existing sessions stay
signed in". Tokens live 30 days, and the reason anyone changes a password on a
publicly reachable instance is that they believe someone else holds one — so the
action did nothing about the thing it is for.
Now rotates the secret **and returns a replacement token**, so only *other*
sessions die. That preserves the original intent (don't log the owner out of their
own browser) without leaving a suspected intruder signed in, which is why this is
a fix rather than an override of a deliberate decision.
Touches three files: `auth.change_password` returns `str | None` instead of
`bool`; `/api/auth/password` returns `TokenResponse` instead of `OkResponse`
(**breaking API shape change**, acceptable because the only client is in this
repo); `api.ts` stores the returned token immediately.
Negative control is the load-bearing half: a fix that logged the owner out of
their own browser would pass the revocation assertion and be unusable.
Next: the logged stale-`claimed`-job reconciliation is still not done (needs a
timeout policy — the agent's own transcode ceiling is 12h, so ~24h is the obvious
window). `frontend/` still completely unexamined. `services/` remaining:
autoscan, posters, reset, updates.

### Iter 17 · 2026-08-13 · correctness (audit integrity)
The server half of iter 15. A claim was a **one-way door** — nothing anywhere moved
a job out of `claimed` — so an agent that did the work and then failed to report
left the job claimed for ever and its action recorded as approved-but-never-
executed for work that had happened.
`_requeue_abandoned` now runs on every claim (the agent polls every 60s, so no
scheduler is needed) and returns jobs claimed longer than `STALE_CLAIM_HOURS = 24`
to the queue. The window is chosen from the agent's own encode ceiling of 12h.
Re-queueing is safe for both kinds, which is why it can be automatic: a delete
whose file is already gone reports success rather than erroring, so the second run
is what finally records the truth; a transcode re-encodes and verifies before
swapping, so the worst case is wasted CPU.
**Another false negative caught, same shape as before.** The "a finished job is
never requeued" control passed under mutation because the claim loop already
refuses an *executed action* — so removing the `status == "claimed"` filter changed
the job row to `queued` while the handout stayed `None`. Asserting on the handout
proved nothing; it now asserts on the row. Also fixed an edit that landed the new
assertion in the wrong test entirely.
Next: `frontend/` still unexamined. `services/`: autoscan, posters, reset, updates.

### Iter 19 · 2026-08-14 · correctness + perf (user-visible)
Two bugs in `routes_shows.list_shows`, one of them wrong output rather than slow
output.
**Every show was listed at its rarest resolution.** The map was a dict
comprehension over rows ordered by count descending — and a comprehension keeps
the *last* value written, so the final row (the least common resolution) won every
time. Nineteen episodes of 1080p and one of 480p displayed as 480p. Now takes the
max by count with ties toward the lower rung, matching the rule established in
iter 7.
**Both aggregates scanned the whole TV library on every page.** They join
media_file→episode→season and were ungrouped by page, so an infinite scroll over
30,000 episodes re-scanned everything twice per page. Now the page is fetched
first and the aggregates are scoped to its shows; the library-wide total moved to
a plain `SUM` gated on `page == 1`, like the row count beside it.
Negative control worth keeping: "pick the highest resolution present" also fixes
the rarest-wins bug and is equally wrong the other way — a mostly-SD show with one
HD episode is an SD show.
Next (from the parallel audit, still open): `_persist_plex_shows:390` unscoped
`select(Show)` — once per section, linear, low severity. `_upsert_person` and
`_finalize_counts` both run a query per item inside a loop. `analysis/collections.py:23`
has the same shape.
