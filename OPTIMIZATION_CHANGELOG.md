# Optimization Loop — changelog

Each cycle: 10 changes identified → planned in `docs/optimization/CYCLE_NN.md` →
change-reviewed → implemented → QA + security + bug review → versioned here and
merged. Safety rails hold in every cycle: file deletes stay per-item
approval-gated, dry-run stays the default, AI advises and never decides.

---

## 2607.8.0 — Cycle 08

**Plan:** `docs/optimization/CYCLE_08.md` (10/10 approved after change review, 4 amended).

1. **Decisions restore** — the other half of Cycle 7's backup. `POST
   /api/import/decisions` previews by DEFAULT ("would set 1 keep-override, 1
   unknown skipped…") and applies only on the explicit confirm flag; unknown
   tmdb ids are counted and skipped, never invented; thresholds go through the
   validated store; the counts cache invalidates on apply. Settings › Storage
   gains the file-picker → preview → confirm flow. Restore touches keep flags,
   must-have status, and thresholds only — never files, never Radarr.
2. **Poster cache ceiling** — 500 MB cap enforced after each write, oldest-first
   eviction that never touches the file just written (test-pinned).
3. **Library section filter** — new `GET /api/movies/sections` + a dropdown
   (hidden with ≤1 section); the CSV export inherits the filter for free.
4. **The UI remembers your view** — Library grid/table + sort and Junk's sort
   persist to localStorage, with invalid stored values falling back safely.
5. **Esc cancels a thinking Ask** — keyboard parity with the Cancel button.
6. **Connection URLs normalize** — trailing slashes trimmed, missing schemes get
   `http://`, https always preserved; applied on save AND on overlay so stale
   stored values heal too (test-pinned).
7. **Dismissed must-haves can come back** — "Dismissed (N)" strip with per-title
   Restore (`POST /api/musthave/{id}/restore`); a mis-click is no longer forever.
8. **Ring gauges respect reduced motion** — the stroke transition rides `--dur`.
9. **Backups carry their date** — `sift-decisions-2026-07-23.json`,
   `sift-library-2026-07-23.csv` (test-pinned pattern).
10. **Loading states announce themselves** — `aria-busy` + polite hidden
    "Loading…" on Library, Junk, and Activity.

**QA:** 176 backend tests green (7 new — import preview-vs-apply with
unknown-id skipping and threshold restore, sections endpoint, dated filenames,
URL normalization on save + overlay, poster eviction with newest-survives,
dismiss/restore roundtrip). ruff + bandit ruleset + mypy strict clean; tsc +
build + npm audit clean. Live seeded-server: sections, import preview leaving
state untouched, dated Content-Disposition, and the Settings backup/restore UI
verified by screenshot.

**Security review:** the import is the cycle's one new write surface and was
reviewed as such — preview-by-default, explicit apply flag, field-by-field
validation, can only touch keep flags/must-have status/thresholds (never files,
never Radarr), same auth as every gated route; eviction deletes only inside the
cache dir; URL normalization never downgrades https.

**Bug review:** cycle diff re-read line-by-line; caught pre-merge: the sections
route had to be declared before `/movies/{tmdb_id}` so "sections" never parses
as an id; the musthave test fixture yields a bare client (unlike test_api's
tuple) — test fixed to take `factory` separately; `DecisionsImportResult`
missing from api.ts imports (tsc caught it).

---

## 2607.7.0 — Cycle 07

**Plan:** `docs/optimization/CYCLE_07.md` (10/10 approved after change review, 4 amended).

1. **The scan panel shows what it's counting** — the streamed per-phase counts
   ("Reading Plex catalog · plex items 1,234") render inline on active/done
   phases; the polling fallback carries them too, so a blocked websocket loses
   nothing.
2. **Poster fallbacks say which film they are** — the gradient placeholder
   shows the title's initial; grids, search rows, and Missing cards pass it.
3. **Decisions backup** — `GET /api/export/decisions.json` downloads
   keep-overrides, dismissed must-haves, and tuned thresholds (with titles, so
   the file reads as a document), token-in-query like the CSV. Settings ›
   Storage gains the button. Export only — restore is a write surface for a
   future reviewed cycle.
4. **Vendor chunk** — React/router split into an immutable `vendor` chunk;
   the app chunk dropped 222 kB → 59 kB, so app deploys no longer invalidate
   framework bytes.
5. **Junk discloses its cap** — "Showing 200 of N flagged titles" with a
   bounded "Load all" (≤1000) when the fetch cap bit; no more silent
   truncation.
6. **Expand all breakdowns** — one toggle audits every candidate's signals.
7. **Long curated lists fold** — first 12 with "Show all (N)".
8. **Ask can be cancelled** — the thinking bubble gains Cancel (AbortController
   through the API client); cancelling drops the pending bubble and returns
   the question to the input.
9. **Health dots lead to the fix** — the header dot group opens Settings.
10. **Gauges get accessible names** — `role="img"` + labels on RingGauge and
    HealthOrb.

**QA:** 169 backend tests green (1 new — decisions export incl. 401-without-token
negative control, keep/dismissed filtering, thresholds presence). ruff + bandit
ruleset + mypy strict clean; tsc + build + npm audit clean; vendor split
verified in build output. Live seeded-server: decisions export verified (401
without token, correct payload shape); screenshots verified the junk toolbar
(sort + expand-all with breakdowns open) and the Settings backup button.

**Security review:** the new export uses the same explicit token auth as the
CSV (pinned 401 without it) and contains only the owner's own decisions — no
secrets, no connection details; no new write surfaces (import deliberately
deferred); abort handling cannot leave orphaned UI state (finally clears the
controller).

**Bug review:** cycle diff re-read line-by-line; caught pre-merge: the poll
fallback needed to populate phase counts too (websocket-only would go blank
behind proxies); the expand-all toggle had to compare against `items`, not
`pending`, so decided rows don't strand the button in the wrong state.

---

## 2607.6.0 — Cycle 06

**Plan:** `docs/optimization/CYCLE_06.md` (10/10 approved after change review, 4 amended).

1. **Ask compare mode, made real** — the long-dead `mode: "compare"` flag now
   works: under tandem, one deterministic retrieval is phrased by BOTH providers
   concurrently and shown side by side, each labeled with model + latency. The
   alternate failing degrades to a single answer (test-pinned); single mode is
   byte-identical to before (test-pinned). The toggle only appears when the
   server reports both providers usable (`ai_compare_available`). Advisory rules
   unchanged — compare adds a phrasing surface, never a decision.
2. **Activity links to the movie** — action rows' "#id" opens the movie drawer.
3. **Scan receipts** — Activity's scan rows expand to per-phase checkpoint
   status, counts, and the error text for failed runs.
4. **Decided junk rows collapse** — kept/removed titles shrink to a one-line
   strip with an undo, keeping the undecided queue on screen.
5. **Junk sorts by score or size** — a client-side toggle; score (the
   safety-relevant order) stays the default.
6. **Recently added** — a dashboard poster strip of the six newest arrivals
   (one fetch, no polling; hidden when empty), with drawer click-through.
7. **A footer that says what's running** — "Sift {version} · changelog" from
   `/api/version`.
8. **Search shows ownership** — result rows carry "In Plex" (green) or a muted
   "Radarr" tag.
9. **Slow requests get logged** — >500 ms API requests log method + path +
   status + duration at WARNING. Paths only — query strings (which can carry
   download tokens) never reach the log.
10. **Wizard readiness line** — "N of 4 sources verified" derived from the test
    results already in the form; no auto-probing.

**QA:** 168 backend tests green (3 new — compare returns a labeled alternate,
compare degrades when the alternate dies, single mode never carries one).
ruff + bandit ruleset + mypy strict clean; tsc + build + npm audit clean. Live
seeded-server: `ai_compare_available` correctly false without providers, single
ask unchanged, version endpoint feeding the footer; screenshots verified the
expanded scan receipts, linked action ids, collapsed kept-row strip, sort
toggle, footer, and the recently-added strip; seed state restored after QA.

**Security review:** compare builds the second provider per-request and closes
it (no client leaks); no new endpoints beyond reading `/api/version` (already
public); the slow-request log deliberately excludes query strings so poster/CSV
tokens can never land in logs; wizard readiness reads local state only.

**Bug review:** cycle diff re-read line-by-line; caught pre-merge: the compare
gather needed `return_exceptions` so a dead alternate can't sink the primary;
`OllamaProvider` import path (lives in `ai/ollama`, not `ai/provider`); the
decided-row early return made the old in-row decision branch dead code —
removed rather than left to rot.

---

## 2607.5.0 — Cycle 05

**Plan:** `docs/optimization/CYCLE_05.md` (10/10 approved after change review, 6 amended).

1. **A crashed page no longer kills the app** — a route-level React error
   boundary keeps the shell alive, offers Try again / Reload, resets on route
   change, and rethrows to the console.
2. **Choose where Radarr adds go** — Settings › "Radarr add defaults" offers the
   real root folders + quality profiles (new `/api/settings/radarr_options`,
   ids/paths/names only); saved choices win, and a stale choice (deleted
   profile, removed folder) silently falls back to first-of-each so an add
   never fails from drift (test-pinned).
3. **Export the visible library as CSV** — `GET /api/movies.csv` shares the
   exact filter/sort builder with `/api/movies` (they can't drift), streams
   row-by-row, caps at 20k rows, and takes the token as a query param like the
   poster route. Library header gains "Export CSV".
4. **Mobile pass at 375 px** — audit-driven: the header search gets its own
   full-width row on phones (it was simply hidden), and the Run-scan CTA no
   longer wraps to two lines. Everything else already stacked cleanly.
5. **Grids stop re-rendering on scroll** — `React.memo` on `GridTile` and the
   shared `Poster`; appended pages leave existing tiles untouched.
6. **Readable Ask answers** — a deliberately tiny formatter (paragraphs,
   bullet/numbered lists, **bold**; anything else stays literal) replaces the
   pre-wrap blob. Pure function, no dependency.
7. **Fill a collection in one click** — "Add all missing (N)" walks the existing
   per-title add action sequentially with live progress; a failure stops and
   names the title. Same staging/dry-run semantics as a single add.
8. **Posters are warm after a scan** — a COMPLETED scan pre-fetches artwork for
   the first Library page (bounded 36, best-effort, skipped without TMDB,
   never on interrupted/failed runs — test-pinned).
9. **Login remembers you** — the username (never the password) prefills from
   localStorage and focus lands on the password field.
10. **Skip-to-content + landmarks** — a focus-revealed skip link, labeled
    primary nav, `<main id="content">`.

**QA:** 165 backend tests green (3 new — saved-defaults preference + stale
fallback, CSV auth/filters/escaping/GB rendering, poster-warm bound + no-TMDB
skip). ruff + bandit ruleset + mypy strict clean; tsc + build + npm audit
clean. Live seeded-server: CSV verified end-to-end (401 without token, filters
respected, proper quoting), radarr_options degrades to empty when unreachable;
formatter behavior verified by script; mobile screenshots re-taken after fixes.

**Security review:** CSV export enforces the same token auth as the API (401
pinned); radarr_options exposes ids/paths/names only, never keys; the saved
add-defaults flow reuses the existing config store (no new secret surface);
error boundary reveals no stack traces in the UI.

**Bug review:** cycle diff re-read line-by-line; caught pre-merge: the CSV route
originally sat under the router-wide auth dependency (which can't read
query-param tokens — moved to its own router with explicit auth, mirroring
posters); `build_movie_stmt` initially shipped with an invalid type-ignore
(typed properly instead); Ask's era suggestion had already been fixed to use
the dominant era, confirmed intact.

---

## 2607.4.0 — Cycle 04

**Plan:** `docs/optimization/CYCLE_04.md` (10/10 approved after change review, 5 amended).

1. **Health probes stopped hammering dead hosts** — the full connection sweep
   behind `/api/health` and `/api/settings` is cached 15 s and invalidated on
   connection saves and tests (which always probe live). Live measurement:
   774 ms → 10 ms on the second poll.
2. **Hidden tabs stop polling** — status/health poll ticks skip while the tab is
   hidden; returning to the tab refetches immediately so it's never stale.
3. **Infinite scroll without repeated aggregates** — `/api/movies` computes
   COUNT/SUM totals only on page 1; scroll pages skip them and the client keeps
   the page-1 header values (test-pinned).
4. **Ring gauges that mean something** — Watched now gauges *distinct watched
   titles* (new `watched_titles` count) against owned; Pending gauges against
   the whole actionable queue so the ring drains as you work it.
5. **Search admits a miss** — zero hits show "No titles match — Enter searches
   the Library page" instead of nothing.
6. **Failed scans offer Retry** — the scan panel's failure state gains a button
   that relaunches (resuming from checkpoints server-side).
7. **Keyboard navigation** — `g` + `d/l/m/j/a/t/s` jumps between pages; `?`
   opens a shortcuts overlay. Suppressed while typing or while any dialog is
   open; the chord decays after 1.5 s.
8. **Honest connection states** — Settings distinguishes "Not set up" (neutral,
   with a nudge) from configured-but-unreachable (red, with the probe detail).
9. **Ask stays in flow** — the input keeps focus after send; "New conversation"
   clears the thread and restores the suggestion chips.
10. **Deeper activity history** — "Show more" grows the timeline window
    (80 → … → 960, capped); the server now also bounds the limit (422 past
    1000).

**QA:** 162 backend tests green (2 new — page-1-only aggregates, health-cache
hit + invalidation-on-save). ruff + bandit ruleset + mypy strict clean; tsc +
build + npm audit clean. Live seeded-server sweep verified `watched_titles`,
the health-cache timing, page-2 zeroed totals, and the activity bound;
screenshots + a scripted chord-nav assertion verified the shortcuts overlay,
g-l navigation, the no-match row, and the dashboard gauges/deductions.

**Security review:** no new endpoints; the health cache stores probe summaries
only (no secrets); activity limit now server-bounded; shortcut handler ignores
modifier combos and never runs while typing or with a dialog open.

**Bug review:** cycle diff re-read line-by-line; caught pre-merge: the page-2
aggregate skip would have broken the client's `done` detection (it compared
against the now-zero total — replaced with an items-length check); Escape now
closes the help overlay even when a dialog check would otherwise suppress it.

---

## 2607.3.0 — Cycle 03

**Plan:** `docs/optimization/CYCLE_03.md` (10/10 approved after change review, 5 amended).

1. **Auditable library health** — the placeholder score is gone. Health now starts
   at 100 and subtracts *named* deductions (junk backlog and quality-cutoff share
   scaled to the library, small fixed hits for missing integrations), each shown
   under the orb. Deterministic; no AI involvement.
2. **Status polls stopped re-scoring the library** — the queue counts behind
   `/api/status` (polled every 8 s) are cached in-process (30 s TTL as a backstop)
   and explicitly invalidated on keep-overrides, threshold saves, must-have
   runs/dismissals, and scan completion — a Keep click still drops the count on
   the very next poll (test-pinned).
3. **Login brute-force guard** — >5 failed attempts on an account within 60 s →
   429 with `Retry-After`; keyed by username (not IP — proxies collapse those),
   cleared by a successful sign-in. Live-verified: 401×5 → 429, other accounts
   unaffected.
4. **Mid-session sign-out** — a dead token now drops the app to the login screen
   (the API client clears it and signals the auth gate) instead of leaving every
   page silently broken. Login endpoints excluded, so a wrong password can't loop.
5. **Table-view column sorting** — Title/Year/Size headers sort (click to flip),
   with `aria-sort` and a direction arrow, synced with the sort dropdown; the
   table also gained a Size column.
6. **What pruning is worth** — the Junk header shows the flagged queue's total
   reclaimable disk ("~184 GB reclaimable"); the selection bar shows the size of
   the current selection.
7. **Errors you can see** — a shared one-at-a-time error toast; failed Keep saves
   now roll the row back and say so, failed removals/dismissals/weight-saves
   report instead of failing silently. Errors only — success stays visible as
   state change.
8. **Snapshot freshness** — the Dashboard subhead says when the data was last
   refreshed and flags a stale snapshot once it outlives 2× the rescan interval.
9. **Route-level code splitting** — each page is a lazy chunk behind a Suspense
   boundary *inside* the shell (nav never flashes away); the main bundle dropped
   272 kB → 216 kB.
10. **Multi-select accessibility** — the Junk action bar is a labeled toolbar
    with a polite live region for the selection count (row checkboxes already
    carried accessible names).

**QA:** 161 backend tests green (3 new — rate-limit trip incl. right-password
lockout + per-account isolation + success reset, cache invalidation via keep and
dismiss writes). ruff + bandit ruleset + mypy strict clean; tsc + build clean
(9 lazy chunks); npm audit clean. Live seeded-server sweep verified the limiter
(401×5 → 429 with Retry-After 60), cache invalidation end-to-end in both
directions, and screenshots verified health deductions, freshness, table
sorting, and junk totals.

**Security review:** rate limiter fails closed per-account and cannot lock out a
legitimate owner permanently (60 s window, success clears); 401 handling never
fires on auth endpoints (no redirect loops); cache holds only two integers (no
user data); no new endpoints; headers/gzip posture unchanged.

**Bug review:** cycle diff re-read line-by-line; issues caught and fixed
pre-merge: Suspense originally wrapped the whole router (shell flashed away on
chunk loads — moved inside the shell); Toast import/mount mismatch; removal loop
had no failure surface (errors now toast and leave remaining rows undecided).

---

## 2607.2.0 — Cycle 02

**Plan:** `docs/optimization/CYCLE_02.md` (10/10 approved after change review, 4 amended).

1. **Dashboard that tells you what's next** — "Needs your attention" is now
   state-driven: junk queue and pending Must-Have picks (with live counts, from
   the new status fields), quality-cutoff upgrades, then missing integrations
   (TMDB / Tautulli / AI provider) and the ephemeral-storage warning. Unconfigured
   is distinguished from momentarily-unreachable — only genuinely missing setup
   earns a "connect it" card.
2. **Taste weights do something** — the Taste Profile's genre and era sliders now
   steer the Recommended-for-you ranking: a bounded multiplier (≤1.5×) that only
   ever *reorders* TMDB-grounded candidates, never gates one in or out. Sliders at
   zero reproduce the unweighted order exactly (pinned by test). Copy updated to
   say so.
3. **Search that answers in place** — the header search shows the top 5 matches
   inline with real poster thumbs; click opens the movie drawer, arrow keys +
   Enter work, stale responses can't clobber newer keystrokes (latest-wins), and
   the debounce is 250 ms.
4. **Ask chips from your own shelves** — the suggestion chips are built from the
   library profile (top genre, top director, dominant era) with the old static
   list as a pre-scan fallback.
5. **Scan history** — Activity shows the last 5 scan runs (status, when, duration,
   headline counts), so automatic rescans are finally visible.
6. **Security headers** — every response carries `X-Content-Type-Options:
   nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`. CSP
   deliberately deferred (inline-styled SPA) and its absence is test-pinned.
7. **Empty states with a way forward** — `EmptyState` gained an action slot:
   Library empty → Run scan / Clear filters, Junk empty → Adjust scoring
   thresholds, Activity empty → open the Junk queue, Dashboard all-caught-up →
   Refresh the snapshot.
8. **Poster loading hints** — shared `Poster` adds `decoding="async"` alongside
   `loading="lazy"`; long grids decode off the main thread.
9. **GZip** — JSON responses ≥1 KiB ship compressed (`GZipMiddleware`); tiny
   payloads stay uncompressed (test-pinned negative control).
10. **Actionable queue counts** — `/api/status` counts gained `junk_flagged`
    (computed through `junk.candidates`, so keep-overrides and the kids-guard are
    respected — the number always matches the Junk page) and `musthave_pending`
    (suggested, not dismissed, not meanwhile-owned).

**QA:** 158 backend tests green (4 new — taste-weight reorder golden ordering with
zero-weight equivalence, security headers incl. pinned CSP absence, gzip
large/small split, queue counts with keep-override + dismissed/now-owned negative
controls). ruff + mypy strict clean; frontend tsc + build clean; live seeded-server
sweep verified counts, headers, gzip behavior, and scan list; screenshots verified
dashboard cards, Activity scans, profile-derived Ask chips, and the search
dropdown.

**Security review:** new middleware is header-only (no request-body handling); no
new endpoints; gzip bounded by minimum_size (no compression of tiny secrets-adjacent
payloads); `ruff --select S` (bandit ruleset) clean on app code; `npm audit
--omit=dev` clean. Taste steering reads only local DB state.

**Bug review:** cycle diff re-read line-by-line; issues caught during the pass and
fixed pre-merge: Ask era chip used the chronologically-first era instead of the
dominant one; Activity scan stats used wrong key names (`total_movies`/`in_plex`);
global search fallback gradient replaced with the shared `Poster` (keeps the
graceful-fallback path).

---

## 2607.1.0 — Cycle 01

**Plan:** `docs/optimization/CYCLE_01.md` (10/10 approved after change review, 5 amended).

1. **Credentials that stick** *(owner-reported)* — login + wizard forms carry the
   `name`/`id` attributes password managers require, so browsers finally offer to
   save the Sift login. Settings › Account warns when the instance runs SQLite on
   an ephemeral host (login/config reset on redeploy) and points at the Postgres fix.
2. **Password change** — Settings › Account form; verifies the current password,
   keeps sessions signed in; no more factory reset to rotate a password.
3. **Clear saved connections** — per-service two-step "Clear saved / Really clear?"
   button; a dead Ollama URL (or any stale key) can finally be removed from the UI.
4. **Automatic rescans** — Settings › Autonomy: Off / 6h / 12h / Daily. Anchored to
   the last completed scan; never double-runs; skips when Plex isn't connected.
5. **Junk multi-select** — checkboxes with a sticky action bar: Keep all selected /
   Approve removal (N). Removals still funnel through the same confirm + per-item
   approval.
6. **Library totals** — header shows the filtered set's title count and total disk
   size ("1,234 of 2,000 · 4.2 TB").
7. **Faster Must-Have runs** — candidate validation now fans out (bounded, 6 wide)
   under TMDB's rate limiter; runs complete several times faster with identical,
   order-stable results.
8. **Drawer accessibility** — Esc closes the movie drawer; focus moves in on open
   and returns to the opener on close.
9. **Readable Activity** — relative timestamps (absolute on hover), payload JSON
   collapsed behind a toggle, staged actions labeled inline.
10. **Poster cache management** — Settings › Account shows the cache's file count
    and size with a Clear button; posters refill on demand.

**QA:** 154 backend tests green (10 new — password lifecycle incl. old-password
death + session survival, autoscan due/guard logic, schedule validation, poster
stats/clear, filtered total-size, connection clearing). ruff + mypy strict clean;
frontend tsc + build clean; key screens visually verified.

**Security review:** all new endpoints sit behind the auth gate; password change
re-verifies the current password server-side; poster clear touches only `*.img`
files inside the cache dir; no secrets in new logs or error surfaces; `ruff
--select S` (bandit ruleset) clean; `npm audit --omit=dev` clean.

**Bug review:** cycle diff re-read line-by-line; issues found during the pass
(stale test fixture shape, autoscan test racing a real network call) fixed before
merge.
