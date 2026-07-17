# STATE — Sift

Resume point + working decisions. Read after `CLAUDE.md`.

---

## Where we are

**MVP merged (PR #1); refinement wave in flight on PR #2** (branch
`claude/sift-webapp-setup-2qmxsn`, restarted from main post-merge). This wave adds:
**AI engine modes** (tandem / Claude only / local only; `registry.build_providers`
is the single source), **verified-key Anthropic model picker**, the **Must-Have
catalog** (AI proposes canon titles, deterministic TMDB gates decide — migration
0005), **login-first front door**, **silent wizard first scan** + idempotent
`POST /api/scan`, scan phases Plex→Radarr→Tautulli→TMDB→finalize→score→**AI
analysis**, and **persistent keep-overrides** (migration 0006).

Green gates (run from `backend/` in the venv at `../.venv`):

```bash
# from backend/ :
ruff check .            # clean
../.venv/bin/mypy sift  # strict, clean (73 files)
../.venv/bin/pytest -q  # 139 passed
npm --prefix ../frontend run build   # clean (tsc --noEmit && vite build)
# from the repo root (alembic.ini lives there; script_location=backend/sift/db/migrations):
./.venv/bin/alembic upgrade head     # 0001→0006, idempotent over create_all
```

The delete-safety test is mutation-verified: disabling the guard in
`actions/engine.py` fails `test_actions_safety.py` (negative control has teeth).

### Owner-requested upgrades (latest) — all browser-verified
- **Login + Setup Wizard + in-app config.** Single-user auth (stdlib pbkdf2 + signed
  session tokens). Wizard: create login → connect + Test each service → done.
  Connections (Plex/Radarr/TMDB/Tautulli/Ollama/Anthropic) entered in the UI, stored
  in the DB, overlaid on env/toml, rebuilt live on save. Settings › Account has
  sign-out + **Reset** (full / keep-thumbnails).
- **Thumbnails**: server-side poster cache (`/api/poster/{id}`) fixes Plex-only
  titles; **Library A–Z rail** jumps by first letter.
- **Smarter junk**: classifier cascade (adult/cult/US-theatrical/independent/
  international) over the score, fed by TMDB facts (migration 0003; `enrich_limit`).
- **Curated lists** (migration 0004): cult + IMDb-top starter lists (pending review),
  resolved via TMDB search; feed the cult rule + Missing "you don't own these".
- **AI review**: Ollama drafts → Anthropic refines, advisory-only; "Run AI review"
  on the Junk screen. Degrades to a deterministic note with no providers.
- **Add/monitor/remove in the UI**: the movie drawer exposes Monitor/Unmonitor +
  confirm-gated Remove; Missing exposes "+ Add". `POST /api/actions/add` resolves the
  Radarr root folder + quality profile for live adds. Engine dispatches to Radarr on
  the stored `radarr_id` (not `tmdb_id`) and refuses titles Radarr doesn't manage.
- **Taste recommendations** (`analysis/recommend.py`): TMDB discovery graph seeded by
  your highest-rated owned titles; aggregated, ranked, and explained; owned titles
  excluded. Deterministic — degrades to a connect-TMDB / run-a-scan note.
- **Write mode toggle** (Settings › Autonomy): staged vs live, persisted via
  `config_store.set_actions` and re-overlaid on `runtime.rebuild`. **Density toggle**
  now actually drives the library table row spacing.
- **Audit pass** over the new action/recommendation code (subagent + fixes): Missing's
  not-yet-owned posters link to TMDB (were opening a 404 drawer); recommendations show
  a "couldn't reach TMDB" note when every anchor call fails (was "covers the graph
  well"); live add returns 400 not 500 on an unreachable Radarr; drawer monitor/
  unmonitor records `actor=user`. Safety machinery (delete guard, dry-run authority,
  radarr-id resolution) audited clean.

### Upgrade detector (cutoff-unmet) — latest slice
- `Movie.cutoff_unmet` (migration `0002`, indexed) captures Radarr's "below profile
  cutoff" verdict, read free from the movie payload during the radarr phase.
- `analysis/upgrades.py` + `GET /api/upgrades` + `/api/status` `upgrades` count +
  `/api/movies?cutoff_unmet=` filter. Surfaced in-design: Library "Below cutoff"
  quick filter (`?filter=upgrades`), a table badge, and a Dashboard callout.
- `alembic upgrade head`/`downgrade base` verified; 0002 is idempotent so it applies
  cleanly over the create_all baseline.

### Live action execution (Phase 3) — earlier slice
- `POST /api/actions/{id}/execute` completes the lifecycle over HTTP; the golden
  guard maps to **403** for an unapproved delete (409 already-done, 404 unknown).
- `RadarrWriter(RadarrConfig)` builds a short-lived `RadarrClient` per live write
  and closes it. `SIFT_ACTIONS__DRY_RUN` (**default `true`**) is the master switch;
  the propose endpoint treats it as a floor (a client can stage, never force live).
- `/api/settings` exposes `actions_dry_run`; the **Junk** screen runs propose →
  approve → execute and labels **"Removed"** vs **"Removal staged"**.
- **Live deletes are OFF by default.** They only fire when the operator sets
  `SIFT_ACTIONS__DRY_RUN=false` *and* clicks through the in-app approval.

### Built
- Config (`config.py`): env > `.env` > `sift.toml` > defaults; secrets as `SecretStr`.
- DB (`db/models.py`, `db/session.py`): full §6 snapshot schema; Alembic baseline
  migration `0001_initial` verified (`alembic upgrade head` creates all tables).
- Clients (`clients/`): async httpx base with retry/backoff-with-jitter, rate
  limiting, secret redaction; Plex/Radarr/Tautulli/TMDB with `health()` probes.
- Ingest (`ingest/`): pure normalization + resumable, checkpointed, idempotent
  pipeline (kids-section guard applied at ingest).
- Actions (`actions/`): propose/approve/reject/execute with the **delete =
  approval-required** invariant; dry-run-capable Radarr write wrapper.
- Services (`services/`): health aggregation, audit trail, scan runner.
- API (`api/`): `/api/health`, `/api/status`, `/api/scan[/{id}]`, `/api/movies[/{id}]`,
  `/api/actions[...]`, `/api/activity`, `/api/version`, `/ws/scan/{id}`; token gating.
- CLI (`cli.py`): `sift serve|scan|init`.

### Not yet done in Phase 0 (needs the human / real infra)
- **Real-server verification of a live scan** (`Done when` gate): requires actual
  Plex + Radarr credentials + reachability. The pipeline + no-op scan are tested;
  a live scan against the family server has NOT been run from here.

---

## Frontend (walking skeleton — code-complete, visual-pending)

Built from `docs/design/HANDOFF.md` in `frontend/` (React + Vite + TS + Tailwind).
`npm run build` is clean; FastAPI serves `frontend/dist` at `/` with an SPA fallback;
verified rendering in a real browser across routes + themes.

- Design tokens for all 3 themes, density + reduce-motion, global shell (header /
  top-nav / aurora / scan panel), routing for all 8 screens.
- **All 8 screens are now wired to the real API** — Dashboard, Library (infinite
  scroll), Junk (propose→approve→execute), Missing (collection gaps), Ask (grounded
  retrieval), Taste Profile (buckets + emphasis sliders), Settings (connections +
  editable thresholds + AI/dry-run status), Activity feed, and the live Design System.
  The Movie drawer is live.
- **Visual sign-off pending** (per DoD): the screens are code-complete but need a
  human look, and light/neon token values want a fidelity pass. `dist/` is gitignored
  — run `npm --prefix frontend run build` before serving.

## Next up

1. **Operator verification** on the real server: run a live scan, then exercise the
   Junk queue in staged mode; flip `SIFT_ACTIONS__DRY_RUN=false` only when confident.
   Confirm the upgrade detector lights up (needs a Radarr library with cutoff-unmet
   files) — it's structurally tested but unverified against real Radarr data.
2. **AI depth** once a key + embeddings land: LLM rationale on junk, grounded
   recommendations, Ask streaming + compare.
3. **Visual sign-off pass** across all 8 screens / 3 themes (now incl. the Library
   "Below cutoff" filter + Dashboard upgrade callout).

---

## Working decisions (don't re-litigate without cause)

- **Async httpx clients, not `plexapi`/`pyarr`.** One uniformly async, rate-limited,
  mockable client layer beats wrapping two sync libraries. Swap-in remains possible.
- **Sync SQLAlchemy for the SQLite snapshot.** Network I/O is the slow part and is
  async; DB writes during a scan are pushed to a worker thread (`asyncio.to_thread`).
- **The delete guard lives only in `actions/engine.py`.** One chokepoint, one test.
  The HTTP surface never exposes execute; Phase 0 proposals/approvals are DB-only.
- **Alembic baseline uses `create_all`** so `0001` can't drift from the models;
  later migrations use explicit autogenerated ops.
- **Version:** `2607.0.1` (`YYMM.major.patch`).

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
