# Optimization Loop — changelog

Each cycle: 10 changes identified → planned in `docs/optimization/CYCLE_NN.md` →
change-reviewed → implemented → QA + security + bug review → versioned here and
merged. Safety rails hold in every cycle: file deletes stay per-item
approval-gated, dry-run stays the default, AI advises and never decides.

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
