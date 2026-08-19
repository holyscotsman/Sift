# Sift — engineering guide

The settled decisions, the safety rules, and the map of everything else.
For how the system actually works, read `docs/ARCHITECTURE.md` first.

---

## 1. What this project is

**Sift** is a portable, non-Docker companion to *Butlarr*. It runs anywhere (a
laptop), reaches a self-hosted movie server over the network, reads **Plex +
Radarr + Tautulli + TMDB**, caches a **SQLite snapshot**, then:

- finds **missing** movies (collection gaps + taste-based recommendations),
- flags **junk** worth removing (deterministic score; the LLM only explains it),
- helps **organize**, and answers **natural-language questions** grounded in the
  snapshot.

Butlarr owns the **file plane** (integrity, storage, renames) on the server. Sift
owns the **metadata plane** and runs anywhere. They share **no database**.

---

## 2. How work happens here

- `docs/ARCHITECTURE.md` describes the system as it actually is, cold-readable,
  and is the place to start. This document is the constitution: the decisions
  that are settled and should not be re-argued without a reason.
- Small, reviewable commits; **every behaviour change ships with a test**; no
  destructive action path ships without a guarding test.

---

## 3. Golden safety rule (overrides everything except a worse safety risk)

**A file delete is only ever issued after an explicit, recorded user approval.**
This is a hard invariant enforced by `actions/engine.py` and locked by
`tests/test_actions_safety.py`. Adds/monitors/unmonitors may be autonomous (and are
audited); deletes may not. Never weaken this without a louder test.

---

## 4. Locked decisions

- **Name:** Sift.
- **Form factor:** local web app (FastAPI + browser UI), `uvx`/`pipx`-installable.
  No Docker required (an optional image is a parity nicety, not the primary path).
- **No filesystem access is ever assumed.** All analysis is API-only against the
  cached snapshot; the media server may be offline at any time — degrade gracefully.
- **Autonomy tiers:** add/monitor = autonomous; unmonitor/remove-from-catalog =
  autonomous + audited; **file delete = always explicit approval.**
- **Junk detection is hybrid:** deterministic, vote-weighted data decides the
  score; the LLM only *explains* it and is forbidden from overriding it.
- **Kids guardrail:** items in children's libraries are never auto-flagged for
  removal on adult-rating grounds; they carry a visible guard chip.
- **LLM:** provider abstraction (Local Ollama + Anthropic) with three engine modes
  — **tandem** (local drafts, Anthropic refines — default), **anthropic**, or
  **ollama** — chosen in Settings › Connections. *(Owner revision of the original
  route-by-task / compare / race-fallback trio; the unused embedding slot was
  dropped with it.)* AI is **never** used to decide correctness of a delete or a
  key fact.
- **Version scheme:** `YYMM.major.patch`.

---

## 5. Source-of-truth map (resolve conflicts by this table)

**Plex is the source of truth for library membership** (owner decision, overriding the
original game-plan default that made Radarr the catalog authority). A movie is "in the
library" / "owned" iff it's present in a Plex movie section (`movies.in_plex`). Radarr
is a **management overlay**, not the library definition.

| Source | Authoritative for |
|---|---|
| **Plex** | **Library membership + "owned" (`in_plex`)**, what's playable, per-user watch state, user ratings, kids-vs-adult separation. |
| **Radarr** | Monitored/wanted, quality profile + cutoff, TMDB collection membership, Radarr file state (`has_file`, for duplicate/upgrade analysis) — an overlay, not the library. |
| **Tautulli** | Watch history: plays, last-played, completion. |
| **TMDB** | External ratings + vote counts, collection / keyword / person graph. |

---

## 6. Architecture

- **Metadata plane only.** Ingest via async clients → SQLite snapshot → analysis →
  FastAPI → React UI. Actions go back to Radarr through one audited engine.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, async
  `httpx`. **Frontend:** React + Vite + TS + Tailwind, built to static assets and
  served by FastAPI at `/`.
- **Clients** share `clients/base.py` (retry/backoff-with-jitter, rate limiting,
  secret redaction). *Decision:* Sift talks to all four services with direct async
  `httpx` (not `plexapi`/`pyarr`) so the whole client layer is uniformly async,
  rate-limited, and mockable.
- **Every action** passes through `actions/engine.py`, is recorded with a dry-run
  payload, and only `executed` per the autonomy tier above.

---

## 7. Hard rules for all work

- **Gates:** the test suite is the minimum ship gate. **Negative controls are
  mandatory** on new test pins (a delete-safety test must also prove the unsafe
  path is refused). **Never fabricate a green.**
- **Types:** type hints + `mypy --strict` on the backend; TypeScript strict on the
  frontend.
- **Secrets:** never commit secrets; `SecretStr` for tokens; redact from logs and
  error surfaces. Bind localhost by default; token-gate the API.
- **Performance:** flat-memory streaming ingestion; virtualized tables; target
  smooth handling of 10k+ movies. No unbounded in-memory accumulation in a scan.
- **Resilience:** every client has retry/backoff + rate limiting; a scan survives a
  mid-run server drop (checkpointed, resumable); the UI degrades when a source is
  offline.
- **Commits:** small, per-unit; keep the `YYMM.major.patch` version scheme; no
  timeline estimates in docs or commit messages.

---

## 8. Definition of done (per unit)

Implemented + tests (with negative controls where a safety/exclusion rule exists) +
green **reported honestly** + committed + `CHANGELOG.md` updated.
Visual/UI units are additionally queued for human visual sign-off and marked
"code-complete, visual-pending" until then.

---

## 9. Doc map

- `docs/ARCHITECTURE.md` — how the system works, written to be read cold.
- `docs/SETUP.md` / `docs/DEPLOY.md` — running it, locally and hosted.
- `docs/design/` — the algorithm specs the analysis layer is built from.
- `docs/optimization/HISTORY.md` — what each optimization cycle changed and why,
  with the measured numbers. `LOOP_LOG.md` and `metrics.jsonl` beside it are the
  running record of the continuous-improvement loop.
- `CHANGELOG.md` — release history under the `YYMM.major.patch` scheme.
- `README.md` — user-facing overview.

## 10. Working decisions

Carried over from the running state file. These are settled; they are recorded
here so they are not re-litigated, not so they can be admired.
 (don't re-litigate without cause)

- **Async httpx clients, not `plexapi`/`pyarr`.** One uniformly async, rate-limited,
  mockable client layer beats wrapping two sync libraries. Swap-in remains possible.
- **Sync SQLAlchemy for the SQLite snapshot.** Network I/O is the slow part and is
  async; DB writes during a scan are pushed to a worker thread (`asyncio.to_thread`).
- **The delete guard lives only in `actions/engine.py`.** One chokepoint, one test.
  The HTTP surface never exposes execute; Phase 0 proposals/approvals are DB-only.
- **Alembic baseline uses `create_all`** so `0001` can't drift from the models;
  later migrations use explicit autogenerated ops.
- **Version:** `2607.55.0` (`YYMM.major.patch`). Kept in sync between
  `pyproject.toml`, `backend/sift/__init__.py` and `frontend/package.json` —
  `services/updates.py` scrapes the first to tell users whether they are current.
- **A TV sweep is streamed, never accumulated.** Plex episodes are written every
  `EPISODE_BATCH`, Sonarr shows every `SERIES_BATCH`. Holding a library before the
  first write is what got a scan killed for memory on a hosted instance, and a
  killed scan leaves the run marked running for ever — a bar frozen at the same
  percentage, with no exception anywhere to explain it. **Any new phase that
  reads TV streams too**; the phase after the one you fix has the same shape.
- **Never flush to read an id back mid-loop.** Queue the dependent rows, flush
  the slice once, then attach them. Flushing per parent writes the parent twice —
  an empty insert followed by an update — and stops its siblings batching.
- **Decide narrow, hydrate few.** Where a list is filtered then truncated, the
  filter pass must select only what the decision needs and the wide row read must
  be bounded by the winners. Asking one query for both means the whole table
  crosses the wire so a page of it can be shown. `junk.candidates` is the worked
  example.
- **Page in SQL, count separately.** A `LIMIT`-less read sliced in Python is a
  whole-table read wearing a page's clothing, and it hides behind a correct-looking
  result. Where a total is also needed, a `COUNT` is a second statement, never a
  second read.
- **The client/server seam is tested structurally.** Frontend tests mock `api`
  wholesale and backend tests never see the client, so a renamed route is a 404
  nothing catches. `test_client_routes.py` compares every path in `api.ts` against
  the app's route table; it is mutation-verified from both sides and refuses to
  run against an implausibly small set on either.
- **A screen must never say something reassuring about a failure.** An empty list
  is a claim — "nothing is missing", "every set is complete", "nothing is flagged"
  — and a `.catch` that empties one turns an outage into a lie. Leaving the data
  null is worse still where null is also the loading state: the skeletons stay up
  for ever. Every page-level read names its failure and offers a retry, and every
  such pin carries a control proving a genuinely empty result still reads as good
  news. Checked across all ten screens.
- **One request pays for one request.** Three separate defects had the same
  shape: work proportional to the size of the library behind a request whose size
  never changed — the poster cache statting every cached file to decide whether it
  was over cap, the storage page loading the episode/season/show join once per
  question, and an approval committing and reading back once per file. Local
  SQLite hides all three. Where a cost can grow, pin the *shape* (same statements
  for four times the data), not a number.
- **A shared load is handed in, never mutated.** `tv_size.seasons` and
  `tv_size.inconsistencies` both take `groups`/`shows`; a consumer that popped
  entries as it went would silently empty the second caller's input. The
  equivalence test exists for exactly that.
- **A preload is scoped to what the batch needs, never to the table.** Reading
  every season / episode / media file was free when a phase ran once and is a
  full-table hydration per batch once it runs many times. Neither round trips nor
  hydration cost anything on the file-backed SQLite the tests use, so this is
  pinned structurally: an unfiltered `SELECT` over `seasons` or `episodes` fails
  `test_tv_ingest.py`.
- **`media_files` is reconciled by mark-and-sweep, never per batch.** Rows are
  stamped as they are written and swept once at the end of the phase. A delete
  scoped to a single batch looks correct and is not: the second copy of an
  episode routinely arrives in a later batch than the first, so the batch-scoped
  rule deletes the first copy and destroys the duplicate it was recording.
- **Every long phase reports inside itself.** `_note()` emits a running update
  mid-phase. Without it a slow sweep and a dead process are indistinguishable,
  which is what made the stall above take a round trip to diagnose.
- **Size is judged per hour, never per file.** Bytes/hour bucketed by resolution
  and codec, baselined on the library's own median with MAD for spread. Any rule
  phrased in gigabytes flags the wrong files at both ends.
- **`media_files` is one table for movies and episodes alike**, so every bitrate
  query and outlier rule works on one shape. New tables deploy free under
  `create_all`; new *columns* on an existing table do not.
- **Plex outranks Sonarr and Radarr for files.** They mount the same library at
  different paths, so storing both views doubles the disk being measured.
- **Recognition must never reach the HD/SD decision.** It measures fame;
  SpongeBob is enormously famous and still does not need HD. Pinned by a test.
- **Downgrades need the Sonarr write-back.** Without it the next search undoes
  them, which costs the picture and keeps the disk.

---

## Blockers / for the human

- **Live scan against the real family server** still needs the operator to run it
  with real Plex/Radarr credentials (the `Done when` gate for ingestion).
- **Visual sign-off** on all 8 screens across the 3 themes (per DoD).
- **To enable real deletes:** set `SIFT_ACTIONS__DRY_RUN=false` in Render when ready
  — until then every approved removal is staged (audit-only).
- Optional/gated features still deferred: real AI answers (needs `ANTHROPIC_API_KEY`),
  recommendations + Ask compare panes (need the embeddings layer), watch-history
  signals (need Tautulli).
