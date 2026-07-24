# Changelog

Versioning scheme: `YYMM.major.patch`.

## 2607.10.0 — Overseerr request fix, Missing "Request all", README rewrite

Owner-requested batch:

- **Overseerr requests no longer dead-end.** A title Overseerr already has on file
  answered with HTTP 409, which Sift was treating as a generic "couldn't reach
  Overseerr" failure — a retry could never succeed, so the request looked stuck
  forever. It's now recorded as `already_requested` (shown as "Already requested",
  not an error). A rejected API key now says so explicitly instead of reading like
  a network fault. On the frontend, request/add calls now carry a 30s timeout, so
  a genuinely hung connection surfaces as a retryable error instead of a button
  stuck on "…" with no feedback, and a failed request now names the reason in a
  toast rather than failing silently.
- **Missing gets "Request all missing."** The same one-click bulk-request control
  Collections already had is now on the Missing page too, next to "Refresh
  catalog" — it walks every title currently missing from the Plex library through
  the same Overseerr/Radarr routing as a single request.
- **README rewritten** for a first-time reader: the repo URL is now the second line
  (impossible to miss), followed by a plain-language "what Sift actually does" and
  a numbered "how the workflow works" walkthrough, ahead of the existing technical
  reference material.
- Verified the existing single-user account system already covers "create an
  account, come back later without re-entering everything": signed session tokens
  persist for 30 days in the browser, and every connected service's credentials
  are stored server-side (not re-entered per login). No changes needed there —
  confirmed via the existing auth test suite.

## 2607.9.0 — Missing redesign, Overseerr, theatrical junk rules

Owner-requested batch:

- **Missing, rebuilt.** The backend now keeps a private canon of theatrical-scale
  films worth owning — TMDB's top-rated chart, a revenue-sorted blockbuster
  sweep, the curated lists (cult / IMDb top / criterion), and gated curator
  picks. The Missing page shows only the difference against the **Plex library**
  (Radarr is deliberately ignored) as a poster grid with per-title Request
  buttons and a "Refresh catalog" action. The canon itself stays backend-only.
- **Collections is its own page** (nav item between Missing and Junk) with the
  same gap view as before plus one-click "Request all missing".
- **Overseerr integration.** New connection (Settings › Connections + wizard +
  health dot). When configured, every add-request routes through Overseerr's
  approval pipeline; otherwise it falls back to a direct Radarr add. The server
  dry-run floor applies to both paths, and every request is recorded in the
  audit trail with its route.
- **Junk keeps theatrical-scale releases.** The protection now covers US
  theatrical runs, major-studio releases (Disney, Amazon, Netflix, …) even when
  streaming-only, and studio-scale budgets (≥ $20M) — famously bad big films are
  kept on purpose. Junk stays aimed at low-budget, independent, and non-theatrical
  international titles. Takes full effect after the next scan re-enriches. All
  flagged candidates now start **selected for removal** by default (nothing is
  sent until Approve + confirm), and every row carries an **IMDb ↗** link.
- **Thumbnails fixed.** Radarr-relative poster paths (/MediaCover/…) are no
  longer stored, stored-but-dead poster URLs now fall back to a TMDB lookup and
  heal themselves, so artwork resolves for every title with TMDB connected.
- **Header polish.** A bigger, sharper Sift wordmark, and the previously-dead
  three-line button is now a real menu (row spacing, theme, keyboard shortcuts,
  changelog, sign out). Taste-graph recommendations moved to the Taste Profile
  page.
- **Dependency security:** react-router upgraded v6 → v7.18 to clear
  CVE-2025-68470-adjacent advisories; `npm audit` clean again.

## 2607.8.0 — Optimization Cycle 08

Ten reviewed changes (plan: `docs/optimization/CYCLE_08.md`, log:
`OPTIMIZATION_CHANGELOG.md`): decisions restore with preview-by-default apply
flow, a 500 MB poster-cache ceiling with oldest-first eviction, a Library
section filter, persisted view/sort preferences, Esc-cancellable Ask,
connection-URL normalization (scheme + trailing slashes), restorable dismissed
must-haves, reduced-motion-aware gauges, dated backup filenames, and announced
loading states.

## 2607.7.0 — Optimization Cycle 07

Ten reviewed changes (plan: `docs/optimization/CYCLE_07.md`, log:
`OPTIMIZATION_CHANGELOG.md`): live per-phase scan counts in the panel, poster
fallbacks labeled with the title's initial, a decisions backup download
(keep-overrides + dismissals + thresholds), a vendor chunk (app bundle 222 kB →
59 kB), junk cap disclosure with bounded Load-all, expand-all signal
breakdowns, folding curated lists, cancellable Ask requests, health dots
linking to Settings, and accessible gauge labels.

## 2607.6.0 — Optimization Cycle 06

Ten reviewed changes (plan: `docs/optimization/CYCLE_06.md`, log:
`OPTIMIZATION_CHANGELOG.md`): real Ask compare mode (both tandem providers
phrase one retrieval, side by side, graceful degradation), Activity movie-id
drawer links + expandable scan receipts, collapsed decided junk rows, junk
score/size sort, a recently-added dashboard strip, a version footer, ownership
pills in global search, slow-request logging (paths only — tokens never reach
logs), and a wizard readiness line.

## 2607.5.0 — Optimization Cycle 05

Ten reviewed changes (plan: `docs/optimization/CYCLE_05.md`, log:
`OPTIMIZATION_CHANGELOG.md`): route-level error boundary, chooseable Radarr add
defaults (root folder + quality profile with stale-safe fallback), streaming
CSV export of the filtered library, 375 px mobile fixes (search row, no CTA
wrap), memoized grid tiles/posters, a tiny Ask answer formatter, one-click
collection fill with progress, bounded poster warm-up after completed scans,
username prefill at login, and skip-to-content + labeled landmarks.

## 2607.4.0 — Optimization Cycle 04

Ten reviewed changes (plan: `docs/optimization/CYCLE_04.md`, log:
`OPTIMIZATION_CHANGELOG.md`): cached health sweep (774 ms → 10 ms polls) with
save/test invalidation, visibility-aware polling, page-1-only list aggregates,
meaningful ring gauges (new `watched_titles` count), a search no-match row,
scan-failure Retry, `g`-chord keyboard navigation + `?` shortcuts overlay,
honest not-set-up vs unreachable connection states, Ask focus retention +
New conversation, and a growing bounded Activity window.

## 2607.3.0 — Optimization Cycle 03

Ten reviewed changes (plan: `docs/optimization/CYCLE_03.md`, log:
`OPTIMIZATION_CHANGELOG.md`): auditable health score with named deductions,
cached status queue counts with exact write-path invalidation, login
brute-force guard (per-account 429 + Retry-After), mid-session sign-out on dead
tokens, sortable table columns (+ Size column), junk reclaimable-disk totals,
shared error toasts on failed mutations, snapshot freshness + stale hint,
route-level code splitting (272 kB → 216 kB main bundle), and multi-select
toolbar accessibility.

## 2607.2.0 — Optimization Cycle 02

Ten reviewed changes (plan: `docs/optimization/CYCLE_02.md`, log:
`OPTIMIZATION_CHANGELOG.md`): state-driven dashboard attention cards with live
junk/must-have queue counts, taste-profile weights that actually steer
recommendations (bounded reorder, zero-weight equivalence test-pinned), inline
global-search results with poster thumbs + latest-wins fetches, Ask suggestion
chips built from the library profile, scan history on Activity, security headers
(nosniff / DENY / same-origin referrer), empty states with a next-step action,
async poster decoding, gzip for large JSON responses, and `junk_flagged` /
`musthave_pending` status counts that always match their pages.

## 2607.1.0 — Optimization Cycle 01

Ten reviewed changes (plan: `docs/optimization/CYCLE_01.md`, log:
`OPTIMIZATION_CHANGELOG.md`): password-manager-friendly login + ephemeral-host
warning, in-place password change, per-service "clear saved values", automatic
rescans (6/12/24h), Junk multi-select, Library title/disk totals, ~4× faster
Must-Have validation, drawer Esc/focus accessibility, readable Activity
(relative times, collapsed payloads), poster-cache stats + clear. Security pass:
new endpoints gated, bandit ruleset + npm audit clean, narrowing asserts replaced
with explicit raises.

## Unreleased

### Added — refined AI engine, Must-Have catalog, and onboarding flow
- **AI engine modes** (Settings › Connections): **Tandem** (local Ollama drafts,
  Anthropic refines — default), **Claude only**, or **Local only**.
  `registry.build_providers` is the single mode-aware source of providers; review and
  Ask both honor it, and Ask now works on a local-only setup.
- **Anthropic key verification + model picker** — Test calls `GET /v1/models` (free),
  proving the key and returning the models it can use; the model field becomes a
  dropdown of those ids. Rejected keys report "key rejected (401)".
- **Must-Have catalog** (Missing › Must-have picks): the engine studies a profile of
  the library and proposes canon feature films it's missing — acclaimed theatrical
  releases and Criterion-caliber world cinema. Proposals are hints only; nothing is
  stored unless TMDB data clears the anti-nonsense gates (resolves on TMDB / ≥200
  votes / ≥6.5 average / feature runtime / released / not adult / not owned / not
  dismissed). Dismissals are remembered; re-runs never duplicate (migration 0005).
  Without AI, the new Criterion + IMDb-top starter lists (pending human review) feed
  the same gates.
- **Scan flow**: phases reordered to Plex → Radarr → Tautulli → TMDB → finalize →
  score → **AI analysis** (auto advisory review; skips silently with no provider).
  `POST /api/scan` is idempotent (joins an in-flight run; retires stale RUNNING rows).
  The Setup Wizard silently starts the first scan the moment Plex + Radarr test green.
- **Login-first front door** — sign-in is the default screen; "New user? Set up Sift"
  shows only while no account exists.
- **Keep is permanent** — Junk's Keep persists as `movies.keep_override` (migration
  0006): protected titles never re-flag across rescans; drawer shows a Protected pill.

### Fixed
- **A–Z rail drifted off-screen on scroll** — the page container's transform
  animation demoted `position:fixed`; the rail is now portaled to `<body>`.
- Ollama connection hint now gives the one-line cloudflared tunnel command; Junk's
  dry-run note points at Settings › Autonomy instead of an env var.

### Fixed — audit of the new action/recommendation code
- **Dead-end drawer on Missing** — recommendation and curated-list posters opened the
  library drawer, but those titles aren't in the library, so it 404'd to "Not found."
  They now link out to the title's TMDB page (preview before adding), the affordance
  Radarr/Overseerr use for not-yet-owned titles.
- **Misleading recommendations note** — if every TMDB discovery call failed (bad key,
  outage), the user was told their library "already covers the graph well." The engine
  now tracks whether any anchor call reached TMDB and shows a "couldn't reach TMDB"
  note instead.
- **Live add no longer 500s on an unreachable Radarr** — resolving the root folder /
  quality profile is wrapped, returning the same graceful 400 as the empty-config case.
- **User monitor/unmonitor mislabeled as autonomous** — a manual toggle from the drawer
  now records `actor=user` instead of `auto` on the Activity trust surface.

### Added — taste recommendations + polish
- **Real "Recommended for you"** — the Missing screen's recommendations are no longer a
  stub. `analysis/recommend.py` seeds TMDB's discovery graph from your highest-rated
  owned titles (anchors), pulls `recommendations`/`similar` for each, aggregates and
  ranks candidates you don't own, and explains each ("Because you own X and Y").
  Deterministic — TMDB picks the candidates, Sift ranks and explains, never invents.
  `GET /api/missing/recommendations` degrades to a clear "connect TMDB" / "run a scan"
  note when it can't run.
- **Density toggle now does something** — the header's row-density button drove CSS
  variables nothing consumed. The library table now honours it (comfortable vs compact
  rows) and the tooltip says what it does.
- **Ask** — stale "add ANTHROPIC_API_KEY" hint replaced with a pointer to the in-app
  Settings › Connections (config moved into the UI).
- **Connections** — a live inline warning when a service URL points at
  ``localhost``/``127.0.0.1`` on a hosted instance (the #1 Ollama setup gotcha), shown
  before the Test round-trips and fails cryptically.
- **Activity** — added a "monitor" filter chip (monitor actions are common now that the
  drawer exposes them).

### Added — add/monitor/remove actions in the UI
- **Movie actions surfaced in the drawer** — Monitor/Unmonitor toggle + Remove
  (confirm-gated, dry-run aware) on any Radarr-managed title; a clear "not managed by
  Radarr" note otherwise. The **Missing** screen gains "+ Add" on collection gaps and
  starter-list titles. New `POST /api/actions/add` (autonomous, staged unless
  `SIFT_ACTIONS__DRY_RUN=false`) resolves the Radarr root folder + quality profile for
  live adds via `radarr_add`.
- **Fixed an id-conflation bug** — monitor/unmonitor/delete dispatch to Radarr
  endpoints keyed on Radarr's own movie id, not `tmdb_id`. The engine now resolves the
  stored `radarr_id` and refuses (clear error) any title Radarr doesn't manage; the
  golden delete-approval guard is unchanged. Safety tests seed `radarr_id` and assert
  live calls key on it.

### Added — smarter junk, curated lists, and AI review
- **Smarter junk classification** — a rule cascade over the rating score: adult →
  remove; cult classic → keep; US theatrical → keep; low + independent → remove;
  low + international (non-cult) → remove; else defer to the score. Facts come from
  TMDB enrichment (now run per scan, `enrich_limit`): `original_language`, `budget`,
  `is_adult`, `us_theatrical`, `is_independent` (migration 0003). Forced-removals are
  flagged even when well-rated; protected titles are kept even when low.
- **Curated lists** (migration 0004) — cult + IMDb-top starter lists (factual
  title+year, `review_status: pending`), resolved to TMDB ids via search during a
  scan (never hand-coded). Cult membership drives the "keep if cult" rule;
  `GET /api/missing/lists` surfaces list titles you don't own on the Missing screen.
- **AI review** — `OllamaProvider` + a route-by-task orchestration (local drafts →
  Anthropic refines; band-aware deterministic fallback). `POST /api/review/run`
  writes an **advisory** note on each junk candidate (never changes the deterministic
  verdict — §4/§7); the Junk screen gets a "Run AI review" button and shows the note.

### Added — Setup Wizard, login, in-app config, and reset
- **Username/password login** (single-user; stdlib PBKDF2 + stateless HMAC session
  tokens, no new deps). The API gate accepts a session token or the legacy static
  `SIFT_SERVER__API_TOKEN`, and stays open only until an account exists.
- **Setup Wizard** (first run): create the login → connect + **Test** each service →
  done. `AuthGate` now routes first-run → wizard, returning users → login,
  signed-in → app.
- **In-app connections** for Plex/Radarr/TMDB/Tautulli + **Ollama** URL/model and
  **Anthropic** key/model — stored on the server and overlaid on the env/toml base
  (no need to touch Render). `GET /api/config` masks secrets as `*_set` flags;
  `PUT` deep-merges and rebuilds the live services; `POST /api/config/test/{service}`
  probes unsaved values. A **Settings › Connections** editor and the wizard share one
  form (blank secret = keep the saved one).
- **Reset** (Settings › Account): factory-reset back to the wizard, with a
  **keep-thumbnails** variant that preserves the poster cache for fast re-scans.
- Verified end-to-end in a browser: wizard→dashboard, persistence across reload,
  login rejects bad passwords, reset returns to the wizard.

### Added — poster cache + Library A–Z jump
- **Thumbnails now load for every title.** New `GET /api/poster/{tmdb_id}` resolves a
  poster from the stored URL or by TMDB id, downloads it, and caches the bytes on
  disk keyed by id — fixing Plex-only titles (most of the library) that carry no
  Radarr artwork. The route accepts `?token=` so `<img>` tags authenticate; a shared
  `<Poster>` component falls back to the gradient placeholder on 404. Cache dir
  defaults beside the DB (`PostersConfig.cache_dir`) so a persistent disk covers it —
  this is the cache the upcoming "reset (keep thumbnails)" preserves.
- **Library A–Z rail:** when sorted by title, a letter rail jumps straight to titles
  starting with that letter via a new `starts_with` filter on `/api/movies`
  (`#` = digits/symbols). Verified in-browser: filter works, 0 broken images.

### Added — upgrade detector (cutoff-unmet)
- Deterministic **upgrade detector**: library titles whose current file is below
  Radarr's quality-profile cutoff. The verdict (`cutoff_unmet`) is read straight off
  the Radarr movie payload during ingestion — **no extra request** — and stored on
  the movie (migration `0002`, indexed). Kids items are included (an upgrade is never
  a removal, so there's no safety reason to guard them).
- `analysis/upgrades.py` (`candidates` ordered biggest-file-first, `count`), a new
  `GET /api/upgrades`, an `upgrades` figure on `/api/status` counts, and a
  `cutoff_unmet` filter on `/api/movies`.
- Frontend surfaces it in-design (no new screen): a **"Below cutoff"** quick filter
  on Library (deep-linkable via `?filter=upgrades`), an **"↑ upgrade"** badge in the
  table, and an actionable **"N titles below the quality cutoff"** callout on the
  Dashboard linking to the filtered library.
- Tests with negative controls: normalize extracts the flag (and ignores it when
  there's no file); the detector excludes meets-cutoff and non-Plex titles and orders
  by size; endpoint + status-count + Library-filter coverage.

### Added — live action execution (Phase 3)
- `POST /api/actions/{id}/execute` completes the action lifecycle over HTTP. The
  golden guard is preserved: an unapproved delete returns **403** and is never
  issued; already-executed/rejected actions return 409; unknown ids 404.
- `RadarrWriter` now builds a short-lived `RadarrClient` from `RadarrConfig` for
  each live write (add / monitor / unmonitor / delete), then closes it — nothing to
  dispose at shutdown. `ActionsConfig.dry_run` (env `SIFT_ACTIONS__DRY_RUN`,
  **default `true`**) is the master safety switch; the propose endpoint treats it as
  a floor, so a client can opt *into* staging but can never force a live write the
  operator hasn't enabled.
- `/api/settings` reports `actions_dry_run` so the UI can tell the truth. The **Junk**
  screen now runs propose → approve → **execute**, labels the result **"Removed"**
  (live) vs **"Removal staged"** (dry-run), and warns in the confirm dialog when a
  removal is real and irreversible.
- Tests: execute-endpoint approval guard + dry-run floor over HTTP; an end-to-end
  live-delete integration test proving an approved delete reaches Radarr
  (`DELETE /api/v3/movie/{id}?deleteFiles=true`) via a mock transport; and a
  negative control that a writer with no connection refuses (not silently no-ops) a
  live write.
- `docs/DEPLOY.md` documents the staged-vs-live switch.

## 2607.0.1 — Phase 0 foundations

Initial backend skeleton for the read-only ingestion MVP.

### Added
- Project scaffolding: `pyproject.toml` (hatchling, `sift` console script),
  `sift.toml.example`, `.env.example`, `.gitignore`, `README.md`, `CLAUDE.md`,
  and `docs/GAME_PLAN.md`.
- `config.py` — layered settings (env > `.env` > `sift.toml` > defaults) with
  `SecretStr` secrets for Plex/Radarr/Tautulli/TMDB and the server token.
- `db/models.py` — SQLAlchemy 2.x snapshot schema (movies, ratings,
  watch_history, collections, collection_members, people, movie_people, scores,
  profile, actions, scan_runs, settings) + `db/session.py` engine/session helpers
  (foreign-key + WAL pragmas).
- Alembic scaffolding (`alembic.ini`, `env.py`) with an initial migration.
- `clients/base.py` — async `httpx` base with retry/backoff-with-jitter, rate
  limiting, and secret redaction; `plex.py`, `radarr.py`, `tautulli.py`, `tmdb.py`
  clients each exposing a `health()` probe and the endpoints ingestion needs.
- `ingest/normalize.py` (canonical `tmdb_id` identity) and `ingest/pipeline.py`
  (resumable, per-phase-checkpointed scan emitting progress events).
- `actions/engine.py` + `actions/radarr_writes.py` — propose/approve/reject/execute
  with the **delete-requires-approval** invariant and dry-run payloads.
- `services/health.py`, `services/audit.py`.
- `api/` — `routes_health` (`/api/health`, `/api/status`), `routes_scan`
  (`/api/scan`, `/api/scan/{id}`), `routes_movies` (`/api/movies`,
  `/api/movies/{tmdb_id}`), and `ws.py` (`/ws/scan/{id}`); `main.py` app with
  optional static UI serving and API-token gating.
- `cli.py` — `sift serve|scan|init`.
- Test suite with mocked clients and negative controls, including the
  delete-safety invariant test.

### Added — frontend foundation
- React + Vite + TypeScript + Tailwind app in `frontend/`, built to static assets
  and served by FastAPI at `/` (with an SPA fallback so client routes deep-link).
- Design system from `docs/design/HANDOFF.md`: CSS-variable tokens for all three
  themes (Spatial Dark / Light / Neon), density + reduce-motion, the cyan→magenta
  identity, and Bricolage / Hanken / JetBrains Mono type.
- Global shell — floating frosted header (wordmark, `/`-focus global search,
  connection-health dots, density/theme toggles, scan pill, gradient Run-scan CTA),
  floating top-nav, drifting aurora backdrop, and a live scan panel over `/ws/scan`.
- Typed API client + hooks wired to the real backend; **Dashboard** (instrument
  cluster + health orb) and **Library** (grid/table, filters, pagination) read live
  data; **Activity** renders the audit feed; **Design System** is a live token sheet.
- Missing / Junk / Ask / Taste Profile / Settings ship as on-brand placeholders
  pending the Phase 1–2 analysis + AI backends.
- Verified end-to-end: `npm run build` clean, served by FastAPI, and rendered in a
  real browser across routes and themes. **Visual polish pending human sign-off.**
- CI gains a `frontend` job (npm ci + typecheck + build).
