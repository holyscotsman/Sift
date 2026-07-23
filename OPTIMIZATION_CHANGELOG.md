# Optimization Loop — changelog

Each cycle: 10 changes identified → planned in `docs/optimization/CYCLE_NN.md` →
change-reviewed → implemented → QA + security + bug review → versioned here and
merged. Safety rails hold in every cycle: file deletes stay per-item
approval-gated, dry-run stays the default, AI advises and never decides.

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
