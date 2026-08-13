# Sift — how it works

A complete description of the system as it stands at **2607.24.0**, written to be
read cold. If you are picking this up in a fresh conversation with no other
context, this file plus `CHANGELOG.md` should be enough to reason about changes
without re-deriving the design.

---

## 1. What it is, and what question it answers

Sift curates a **Plex media library**. It answers three questions, and they are
genuinely different:

1. **Should this be on the server?** — the junk score. Films only.
2. **What am I missing that I'd want?** — recommendations and "must-have" canon.
3. **Where did my disk go, and what is the safest way to get it back?** — the
   reclaim ledger. Films *and* television.

It reads from Plex, Radarr, Sonarr, Tautulli and TMDB. It writes to Radarr and
Sonarr, and — only through a helper on the media box — to the filesystem.

**Single user.** One login, token session auth. There is no multi-tenancy, no
roles, no sharing.

---

## 2. Runtime shape, and the constraints that follow from it

This section matters more than any other for judging a proposed change. Most
non-obvious decisions in the codebase exist because of one of these three facts.

| | |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 (sync ORM), Python 3.12 |
| Frontend | React + Vite + TypeScript, Tailwind |
| Hosting | Render (Docker), auto-deploys from `main` (`render.yaml`, `autoDeploy: true`) |
| Database | Neon Postgres in production; **file-backed SQLite in tests and locally** |
| Media services | Reached over the network from the Render box, or locally via `docker-compose` |

### Constraint 1 — `create_all` adds tables, never columns

The Dockerfile runs uvicorn directly. **There is no Alembic step on boot.** Schema
comes from `create_all`, which will happily create a *new table* on a live
database and will never add a *column* to an existing one.

Consequences you must respect:

- A new table is free to deploy.
- A new column on an already-deployed table **is not**, and will fail at runtime
  with a missing-column error the moment something selects it.
- This is why `PlexCopy`, `MediaFile` and `FileJob` exist as separate tables
  rather than as columns on `Movie` / `Episode` / `TranscodeJob`. Read
  `db/models.py:371` for the original statement of this.
- Migrations exist (`0001`–`0006`) and are correct, but nothing runs them
  automatically. Treat them as documentation plus a local tool.

### Constraint 2 — round trips are free in tests and dominant in production

Tests run on file-backed SQLite where a database round trip costs essentially
nothing. Production is hosted Postgres over a network where the round trip is the
*only* thing that costs. **An entire class of performance bug is therefore
invisible to the test suite.**

Release `2607.15.1` exists solely because of this: a `session.merge()` per film
made the Plex phase look hung in production while every test passed. `2607.24.0`
found the same shape again in the scoring phase (4.002 statements per film).

The established defences:

- Bulk writes follow the `_persist_plex` pattern: chunked `IN` preload (500),
  `session.add` never `merge`, chunked `delete()` for stale rows.
- Performance is pinned by **counting statements**, not by timing. See
  `test_tv_ingest.py` and `test_scoring_cost.py`, which use
  `event.listens_for(engine, "before_cursor_execute")`.
- `bench/bench_score.py` reports **statements per film** as its headline for the
  same reason; wall clock is the secondary, machine-dependent figure.

There is a mirror-image trap. The **reclaim ledger is CPU-bound, not round-trip
bound** — the whole build is nine statements. There the cost is ORM *hydration*
volume, and the fix is selecting columns rather than entities. Don't apply the
statement-counting lens where it doesn't fit.

### Constraint 3 — AI never decides correctness

Every verdict is deterministic arithmetic over stored facts. AI is advisory only:
it explains and drafts, and its output is never allowed to change a score, a
band, a verdict, or whether something is deleted. `analysis/` contains no model
calls at all.

---

## 3. Data model

`backend/sift/db/models.py`. Twenty-one tables. The ones that carry the design:

**Films**

- `Movie` — PK `tmdb_id`. The film catalog. `in_plex` is the library-membership
  flag; a Radarr-only "wanted" entry has `in_plex=False` and is not scored.
- `Rating` — several per film (tmdb, imdb…). The most-voted one wins.
- `WatchHistory` — per (movie, user) aggregate from Tautulli.
- `Score` — the computed junk score plus a `signals` JSON blob holding each
  signal's contribution and the classifier verdict.
- `PlexCopy` — one row per Plex copy of a film. Exists as its own table because
  of Constraint 1, and it is what makes film duplicates visible at all.

**Television** (added in the 2607.16–20 range)

- `Show` — PK **`tvdb_id`**, because that is what Sonarr and Plex's TV agent both
  key on. `tmdb_id` is carried alongside for TMDB enrichment. Watch aggregates
  (`plays`, `last_played_at`, `mean_completion`, `typical_stream_height`) live on
  this row rather than in a separate table.
- `Season` — carries **`air_year` per season**, which is load-bearing: a show's
  first year is the wrong quality ceiling for its later seasons.
- `Episode` — carries `sonarr_episode_file_id`, the exact test for a
  multi-episode file.

**Files and work**

- `MediaFile` — **one row per file on disk, for films and episodes alike.** The
  load-bearing idea of the whole storage feature: one table means the film
  outlier work and the TV size work share one ingest path, one set of bitrate
  queries and one set of tests. `part_group` distinguishes *split parts of one
  presentation* from *separate copies* — read from Plex's Media/Part model rather
  than inferred, because duration alone cannot tell them apart.
- `Action` — the audit record for anything that changes the world.
- `FileJob` — a unit of work for the host agent (`kind` is `delete` or
  `transcode`).
- `ScanRun` — status plus a free-form `checkpoints` JSON blob per phase.
- `Setting` — UI-entered config, secrets encrypted at rest.

---

## 4. The scan

`backend/sift/ingest/pipeline.py`. `POST /api/scan` →
`services/scanner.launch_scan` → `ScanPipeline.run`.

```
PHASES = (preflight, plex, radarr, sonarr, tautulli, tmdb, finalize, score, ai)
```

Dispatch is by naming convention: a phase is a tuple entry plus a
`_phase_<name>` method. Each phase writes a checkpoint into
`scan_runs.checkpoints` the moment it finishes, so an interrupted scan resumes
where it stopped and a re-run is idempotent (all writes are upserts).

Network I/O is async; synchronous database writes are pushed to a worker thread
with `asyncio.to_thread` so the event loop stays free.

**Division of labour** — this is deliberate and worth preserving:

- **Plex is authoritative for membership and for duplicates.** It is the only
  source that reports several files for one episode.
- **Radarr/Sonarr are authoritative for the canonical file**, quality profiles
  and monitored state, and are where write-backs go.
- **Tautulli is authoritative for watch history.**
- **TMDB is enrichment**, bounded by `tmdb_enrich_limit`.

**Preflight** probes every configured service and *drops* the ones that don't
answer, so a dead Tautulli degrades the scan instead of killing it. It always
re-runs on resume, because reachability is a fact about now.

### Streaming, and why every long phase does it

Three separate releases fixed the same defect in three phases. The pattern is
worth stating once:

> A phase that accumulates its whole result in memory before the first write gets
> killed for memory on a small host. A killed process throws no exception — the
> task simply ceases, and the run stays marked `RUNNING` for ever. To the browser
> that is a progress bar frozen at an identical percentage every time.

- **Plex** (2607.21.0) — episodes stream a page at a time via
  `iter_section_items`, written every `EPISODE_BATCH` (2000).
- **Sonarr** (2607.22.0) — one catalog call plus *two calls per show*, each
  returning every episode and file; written every `SERIES_BATCH` (25).
- **Tautulli** (2607.23.0) — history is *folded* into per-title aggregates as
  pages arrive rather than collected, because history size tracks how much a
  household *watches* rather than how much it owns.

Two related rules that fall out of streaming:

1. **Every long phase reports inside itself** via `_note()`. Without it a
   twenty-minute sweep and a dead process are indistinguishable.
2. **`media_files` is reconciled by mark-and-sweep, never per batch.** Rows are
   stamped `seen_at` as written and swept once at the end of the phase. A delete
   rule evaluated against one batch looks correct and is not: the second copy of
   an episode routinely arrives in a *later* batch than the first, so a
   batch-scoped rule deletes the first copy — destroying exactly the duplicate it
   was recording. (Regression test: put the sweep back in the loop and 4 files
   survive out of 40.)

Pagination everywhere carries two floors plus a hard page cap, because container
headers are a request and not a guarantee: a server that ignores them answers
every page with the first one, and the read never ends.

---

## 5. The analysis layer

`backend/sift/analysis/`. Pure functions, no ORM types in the public signatures,
all deterministic.

### Junk scoring — "should this be here?"

`scoring.py` computes a 0–100 composite from independently weighted signals, each
keeping its own contribution and a human-readable detail:

- **rating** (weight 0.6) — Bayesian, pulled toward a prior of 6.0 on low vote
  counts, so 9 votes barely moves the score.
- **engagement** (weight 0.4) — plays, recency against `unwatched_years`, mean
  completion against `low_completion_pct`.

Bands: `junk ≥ 60`, `borderline ≥ 40`, else `keep`.

`classify.py` overlays a verdict on top of the number — adult / cult /
US-theatrical / independent / international — so the answer is "keep or cut given
what kind of film this is" rather than a bare threshold. A `protect` verdict beats
a low score; a `remove` verdict beats a high one.

`recognition.py` measures *public footprint*. It is deliberately **not** used by
quality suitability, and there is a test pinning that: SpongeBob's footprint is
enormous, so feeding recognition into "does this need to be HD" would push exactly
the wrong show to 4K.

Kids-section items are scored but carry a guard and are never auto-flagged for
removal.

### Bytes per hour — the unit everything storage-related uses

`bitrate.py`. Gigabytes per film and gigabytes per season are both meaningless:
a ten-episode season and a twenty-four-episode season aren't comparable, and
neither are 22-minute and 60-minute episodes.

```
observed_rate = size_bytes / (duration_ms / 3_600_000)
```

Bucketed by **(resolution, codec)** — h265/AV1 run at roughly half h264's bitrate
for equivalent quality, so they get their own buckets. The baseline for each
bucket is the **library's own median**, with **MAD** for spread rather than mean
and standard deviation, because a handful of remuxes would drag a mean and hide
everything else. `MIN_SAMPLES = 8`; below that, seed constants apply.

This is why a raw threshold fails: 30 GB is unremarkable for a three-hour 4K
remux and absurd for a 90-minute 1080p.

**A file already at or below its target efficiency is never proposed for
re-encoding** — that trades real quality for near-zero space.

### Film outliers — both ends

`outliers.py`. Oversized is ranked by excess bytes. Undersized (< 1 GB) is
discriminated by **file duration vs the published runtime**:

| Duration vs runtime | Verdict |
|---|---|
| Agrees, runtime genuinely short | Legitimate short film — **not** a finding |
| Much shorter than runtime | Truncated / sample / trailer — zero-loss delete |
| Agrees, but bitrate far below its bucket | Bad rip — flag for re-acquisition, **zero** reclaimable |

Where runtime is unknown, the outcome is "insufficient evidence", never a delete.

### TV duplicates

`tv_duplicates.py`. Grouped by `(show, season, episode)`, never by title. Three
look-alikes are excluded:

1. **Multi-episode files** — several episodes sharing one
   `sonarr_episode_file_id`. Handled at ingest by identifying a file by *path*.
2. **Split parts** — resolved structurally via `part_group`, not by duration.
3. **Deliberate alternate versions** — reported as their own kind.

Ranked by reclaimable bytes, not copy count, so two duplicated 1080p hours
outrank six duplicated SD ones.

### HD/SD suitability

`suitability.py`. Three signals, combined as a clamp:

1. **Source ceiling, per season** (`_CEILING_BY_YEAR`): pre-2004 → 480p,
   2004–2008 → 720p, 2009–2015 → 1080p, 2016+ → 2160p only where a 4K file
   already exists. Per *season*, because Scrubs began in 2001 on SD video and
   ended in HD. **The year rule can never on its own trigger a downgrade** —
   film-originated shows (TNG, The X-Files, Buffy) have genuine HD rescans it
   would wrongly call upscales. It is used confidently only in the other
   direction.
2. **Visual demand** — anime and nature documentary high; flat western cartoons,
   sitcoms and kids-section content low. This is the SpongeBob-vs-anime and
   Scrubs-vs-Severance split.
3. **Attention** — from Tautulli, per show: completion, plays, recency, and the
   resolution actually *streamed to*. A show only ever watched at 720p on a phone
   doesn't need a 4K master.

**The evidentiary bar is deliberately asymmetric.** An upgrade only costs disk
and is reversible, so one signal suffices. A downgrade destroys quality
irreversibly, so it requires low demand *and* low-or-absent attention *and*
excess above a floor *and* source-ceiling corroboration. Anything short of that
returns **"insufficient evidence — no verdict"**, which is a first-class outcome.

**Inconsistent seasons** are detected separately and need none of that judgement:
an episode whose resolution differs from the season's mode, or whose bitrate is a
MAD-outlier at the same resolution.

### The reclaim ledger — the unifying algorithm

`ledger.py`. Not five reports; **one ranked queue in one currency**. Every finding
normalises to `(bytes_reclaimable, risk_tier, reasons)`.

| Tier | Contents | Nature |
|---|---|---|
| **0 — nothing is lost** | Duplicate files, samples, truncated files, orphans | No quality judgement exists |
| **1 — reversible** | Transcodes, original retained until verified | Undoable |
| **2 — a judgement call** | Quality downgrades | Irreversible; the asymmetric bar applies |

Sorted `(risk_tier, -bytes_reclaimable, kind, target_id)`. **The tier ordering is
the point**: most of the space comes back at tier 0, before a single taste
judgement is made. That is what makes it dependable rather than merely clever.

`plan(target_bytes)` walks the ledger from tier 0 upward and returns the cheapest
set of actions reaching the target — the "I need 500 GB back" button.

### A determinism rule that governs all of this

Two bugs in `2607.24.0` came from the same place, and any new ranking code must
respect both:

- **Never `max(set(values), key=values.count)`.** It reads as "the most common"
  and is, except on a tie, where it returns whichever value `set` iteration
  reaches first — an order derived from Python's per-process hash seed. Use
  `tv_size.dominant(values, rank=…)`, which breaks ties toward the *lowest* rank:
  the lower resolution, the less efficient codec. Both make a proposed downgrade
  look smaller, which is the right way to be wrong about a destructive
  suggestion.
- **Every ranking sort key must be total.** No analysis query specifies
  `ORDER BY`. SQLite returns rowid order — which is why tests can't see this —
  and Postgres promises nothing. Equal-scoring items would swap places between
  page loads, and the page shows only the first 500 findings, so it changes
  *which* findings are shown.

---

## 6. Actions and the safety model

`backend/sift/actions/engine.py`. **This is the only execution chokepoint, and it
must stay the only one.**

```
propose  →  approve  →  execute
```

- `AUTONOMOUS_TYPES = {ADD, MONITOR, UNMONITOR}` — reversible, may execute
  without an approval step.
- `REQUIRES_APPROVAL = {DELETE, TRANSCODE}` — a transcode *replaces a file*, so
  it is destructive and gated exactly as a delete is.
- **`dry_run` is server-authoritative**: `settings.actions.dry_run OR
  body.dry_run`. A client may opt *into* staging and can never force a live
  write. Dry run is the default.
- Approval is **per item**. Every action is one audited row.
- Host-executed work never touches the Radarr writer; it goes through
  `mark_executed_external`, which is audit-only.

`ActionType` uses `Enum(native_enum=False, length=16)`, which compiles to plain
`VARCHAR(16)` with no CHECK constraint — verified against the Postgres dialect —
so adding enum members is safe on a live database.

### The host agent

`tools/sift-agent.py`. Stdlib-only, runs **on the media box**, polls Sift.

Polling rather than a webhook is deliberate: on Render the media box is behind
NAT and is not addressable. `routes_config.py` already documents the related trap
— "localhost is the Sift server, not your machine" — as the number-one cause of a
hosted probe failing.

- `GET /api/agent/claim` hands out only jobs whose `Action` is `APPROVED` with
  `dry_run=False`. Bearer token compared with `hmac.compare_digest`.
- `POST /api/agent/{id}/result` records what actually happened.

Its safety rules, each now pinned by a test:

1. **Deletes are moved to `.sift-trash`, never unlinked.** Empty the trash
   yourself. That delay is the only thing between a wrong approval and a
   re-download.
2. **Never overwrite anything already in the trash.** `shutil.move` replaces
   silently, and a transcode writes its encode out under the source's own name —
   so a later delete of that encode would land on the same trash path and erase
   the original it was protecting.
3. **Never overwrite a bystander.** Re-encoding `film.avi` produces `film.mkv`;
   if a *different* `film.mkv` exists, refuse — checked before anything moves.
4. **Verify before swapping.** Both durations must probe (within
   `DURATION_TOLERANCE_SECONDS = 5.0`) and the output must be at least
   `MIN_OUTPUT_FRACTION = 0.05` of the source. A truncated encode plays, is much
   smaller, and every one of those properties reads as success.

### The re-grab guard — not yet built, and it gates downgrades

A downgraded show that Sonarr still monitors at a high cutoff will be silently
re-upgraded, turning the feature into a treadmill fighting its own automation.
**Every applied downgrade must write the season's quality profile back to Sonarr
in the same approved action.** Until that exists, do not ship applied downgrades.

---

## 7. HTTP surface and frontend

18 routers under `backend/sift/api/`, one per area: `movies`, `shows`, `storage`,
`actions`, `agent`, `scan`, `config`, `settings`, `auth`, `health`, `analysis`,
`ask`, `review`, `musthave`, `profile`, `posters`, `export`, `system`.

Ten pages under `frontend/src/pages/`: Dashboard, Library, Junk, Missing,
Storage, Collections, Activity, TasteProfile, Ask, Settings.

**Films and television are separate tabs** throughout — Library, Missing,
Recommendations. TV libraries include Cartoons, Anime, Game Shows and the rest;
Home Videos are excluded, identified by their Plex **metadata agent**
(`com.plexapp.agents.none`) rather than by name, because they are library type
`movie` and would otherwise pollute both the film library and the bitrate
baselines.

**Junk stays films-only, permanently.** Shows are never scored for removal: a
series is forty hours rather than two, and whether it deserves the space is not a
question Sift has been asked to have an opinion about. TV recommendations are
deliberately fewer than film ones — twenty-four film suggestions is a browse,
twenty-four show suggestions is a second job.

---

## 8. Configuration and secrets

`services/config_store.py`. Connection settings are entered in the browser,
stored in the `settings` table, and **overlaid on top of** the env/toml base, so
a hosted instance is configurable without touching Render.

- Secret fields (`token`, `api_key`, `hook_url`, `agent_token`) are **encrypted
  at rest**; key material lives in the environment, not the database.
- `apply_to_settings` uses `model_copy`, not re-construction — re-instantiating a
  `BaseSettings` would re-read env/.env/toml and clobber the overlay.
- Only known fields per service are accepted.

**SSRF posture.** `BaseClient.__init__` refuses link-local addresses (including
the IPv4-mapped IPv6 form), the known cloud metadata hostnames, and any scheme
that isn't http/https. **Private ranges are deliberately allowed** — Plex and
Radarr live on a home LAN, so blocking `192.168.x.x` would pass every attack test
while making the product unusable. Known residual: a *hostname* that resolves to
a link-local address is not caught.

---

## 9. Testing conventions

```bash
ruff check backend
./.venv/bin/mypy backend/sift     # strict
./.venv/bin/pytest -q             # ~440 tests
npm --prefix frontend run build
```

Two conventions are non-negotiable and explain a lot of the test code:

**Negative controls.** Every pin gets a paired test proving the guard isn't
over-broad. This is usually the more important half: an SSRF guard that blocks
private ranges passes every attack test and breaks the product; a last-copy guard
that refuses all episode deletes passes the data-loss test and makes the duplicate
report useless.

**Mutation verification.** Controls are not merely written — the implementation is
broken, the test is confirmed red, then restored. This session alone caught four
of its own tests being false negatives: a patch that silently didn't apply, test
data where the corrupted value equalled the correct one, a determinism check
comparing two runs *inside one process* (where `hash()` is stable), and an
equivalence dump that returned `[]` because the fixture exercised nothing.

**Benchmarks** live in `bench/`, with a seeded fixture (`bench/fixture.py`)
deliberately shaped like a real library: a long unwatched tail, 1-in-40 size
outliers, duplicated episodes, inconsistent seasons, truncated files, and
legitimate short films that must *not* be flagged. Metrics land in
`.claude/metrics.jsonl`; the running log is `.claude/loop-log.md`.

Note the fixture is load-bearing in non-obvious ways: because baselines are the
library's *own* median, adding television to a fixture moves the 1080p median far
enough that previously-oversized films stop being outliers. That's the design
working, but it means fixture changes invalidate earlier numbers.

---

## 10. Known gaps and where to improve

Honest list, roughly by value.

**Needs an owner decision**

- **Changing a service's `base_url` keeps the stored API key**, so a repointed
  service still receives it. Clearing the secret on URL change is the standard
  protection but costs real UX — fixing a typo would force re-entering the key.

**Not built, and blocking**

- **The Sonarr re-grab guard** (§6). Applied downgrades should not ship without
  it.
- **Cold-storage window** for replaced originals: how many days before
  `.sift-trash` is actually emptied is currently manual.

**Unexamined**

- `frontend/` has had no correctness or performance pass at all.
- The agent's `claim`/`report` HTTP paths are untested; `tick()` swallows every
  exception, so a persistently failing report would spin silently.
- `services/` (auth, autoscan, posters, reset, updates) has had no review pass.

**Known smaller issues**

- Old `Action` rows written before 2607.24.0 record successful deletes as
  failures; history was not rewritten.
- `main.py:189` has a mis-indented `routes_system,` inside the router tuple.
  Harmless, but it looks like a diff artifact.
- `STATE.md`'s "Where we are" narrative is stale — it still describes the
  original MVP wave. The "Working decisions" section below it is current and is
  the part worth reading.

**Deliberately not doing**

- Scoring shows for removal.
- Using AI for any correctness decision.
- Adding paid infrastructure.
- Blocking private IP ranges in the SSRF guard.
