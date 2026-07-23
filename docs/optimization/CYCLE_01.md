# Optimization Cycle 01 — plan

Target version: **2607.1.0**. Ten changes across workflow, UX, performance, and
experience. Safety rails (unchanged, every cycle): file deletes stay per-item
approval-gated, dry-run stays the default, AI advises and never decides.

Each item below carries the implementation instructions, then goes through change
review (approve / amend / reject) before any code is written.

---

## 1. Credentials that stick (owner-reported)

**Problem.** The browser never offers to save the Sift login, and on Render free
tier the account itself vanishes on redeploy — the owner re-enters credentials
constantly.

**Change.**
- Add `name` + `id` attributes (`username`, `password`) to the login form and the
  wizard's create-account form — password managers key on these; without them most
  browsers won't offer to save. Keep existing `autocomplete` values.
- Expose `database_kind` ("sqlite" | "postgres") in `GET /api/settings`. When the
  server runs on SQLite **and** the `RENDER` env var is present (Render sets it),
  show a dismissable warning card on Settings › Account: "Your login and settings
  reset on redeploy — connect a free Postgres (see docs/DEPLOY.md)."

**Files.** `AuthGate.tsx`, `SetupWizard.tsx`, `routes_settings.py`, `schemas.py`,
`Settings.tsx`, types.

## 2. Password change (Settings › Account)

**Problem.** The only way to change the password is factory reset.

**Change.** `POST /api/auth/password {current_password, new_password}` — verifies
current, re-hashes, keeps the signing secret (existing sessions stay valid), 401 on
wrong current, 8+ char floor. Small form in Settings › Account.

**Files.** `services/auth.py`, `routes_auth.py`, `schemas.py`, `Settings.tsx`,
`api.ts`, tests.

## 3. Clear saved connection values

**Problem.** Once a service URL/key is saved it can't be cleared from the UI (blank
fields mean "keep"), so a dead Ollama URL lingers forever.

**Change.** A "Clear saved values" text button on each service card that has any
saved value; it sends `""` for every field of that service (the store already
treats empty string as clear) and resets local state. Confirm via the button's
label swap ("Cleared — Save to apply"? No: it saves immediately via saveConfig and
re-fetches). Ollama clear also flips `local_enabled` off via the overlay (already
does — empty URL → not enabled).

**Files.** `ConnectionsForm.tsx`, `config_store.py` test for the clearing path.

## 4. Scheduled auto-rescans

**Problem.** The snapshot goes stale unless the owner remembers to scan.

**Change.** Settings › Scan section: "Automatic rescan" (Off / every 6h / 12h /
24h), persisted in the `settings` table (`scan_schedule`). A background task
(started in lifespan, cancelled on shutdown) wakes every 15 min; if a schedule is
set, no scan is running, and the last completed scan is older than the interval, it
starts one through the same idempotent path (respects `active_scans`). Never runs
when Plex is unconfigured.

**Files.** `services/settings_store.py`, new `services/autoscan.py`, `main.py`
(lifespan), `routes_settings.py` (get/put), `Settings.tsx`, tests (due/not-due
logic, never-double-run).

## 5. Junk multi-select

**Problem.** Junk actions are one-at-a-time or all-at-once — nothing in between.

**Change.** A checkbox per row + a selection bar ("N selected — Keep · Approve
removal") that appears when any are checked. Keep = persisted keep-override per
selection; Approve removal = the existing confirm modal with the selected subset.
"Approve all" button remains.

**Files.** `Junk.tsx` only (APIs exist).

## 6. Library header stats

**Problem.** No sense of scale — how many titles, how much disk, for the current
filter.

**Change.** `GET /api/movies` response gains `total_size` (sum of file_size for
the filtered set, one aggregate query). Library header shows
"1,234 titles · 4.2 TB" under the current filter; updates with filters.

**Files.** `routes_movies.py`, `schemas.py`, `Library.tsx`, types, test.

## 7. Must-Have validation concurrency

**Problem.** Candidate validation is strictly sequential — up to ~80 serial TMDB
round trips (~15–25 s) while the UI shows "Curating…".

**Change.** Validate with `asyncio.Semaphore(6)` + `gather` (the TMDB client's own
rate limiter still paces requests); keep candidate order when selecting the first
`limit` accepted. Same results, several times faster.

**Files.** `ai/musthave.py`, test asserting order-stable selection.

## 8. Drawer accessibility

**Problem.** The movie drawer can't be closed with Esc and focus is left behind
the overlay.

**Change.** Esc closes the drawer; on open, focus moves to the close button; on
close, focus returns to the previously focused element. `aria-modal` already set.

**Files.** `MovieDrawer.tsx`.

## 9. Activity readability

**Problem.** Every entry dumps its raw JSON payload; timestamps are absolute only.

**Change.** Relative timestamps ("2 h ago", title attr keeps the absolute form);
payload JSON collapsed behind a "Payload" toggle per entry; row summary line keeps
type/status/actor.

**Files.** `Activity.tsx`.

## 10. Poster cache stats + clear

**Problem.** The poster cache grows unbounded and is only cleared by full reset.

**Change.** `GET /api/posters/stats {count, bytes}` + `POST /api/posters/clear`
(auth-gated). Settings › Account "Storage" row: "Posters: 312 files · 84 MB —
Clear". Clearing never touches the DB.

**Files.** `services/posters.py` (stats), `routes_posters.py`, `Settings.tsx`,
`api.ts`, test.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved** | Attributes are inert for auth logic; warning is Render+SQLite-scoped so self-hosters see no noise. |
| 2 | **Approved (amended)** | Re-issue a fresh token in the response so the active session continues seamlessly; do NOT rotate the signing secret (would log out other devices — fine) — keep secret, simplest and least surprising. |
| 3 | **Approved (amended)** | Clear must ask for an inline confirm (two-step button: "Clear saved values" → "Really clear?") — an accidental single click wiping keys is too easy. |
| 4 | **Approved (amended)** | The poller must also skip while `SIFT_ACTIONS` unrelated — no amendment needed there; amended to store `anchor: last completed scan finished_at` rather than wall-clock counters, so restarts don't drift. Interval check uses scan_runs, no new state. |
| 5 | **Approved** | Uses existing endpoints; the destructive path still funnels through the same confirm modal + per-item approvals. |
| 6 | **Approved** | One extra aggregate per list call is acceptable (same filtered subquery). |
| 7 | **Approved (amended)** | Cap in-run TMDB fan-out at Semaphore(6) AND preserve `seen` dedupe semantics — move the `seen.add` into a post-gather ordered pass to avoid a race between concurrent validators. |
| 8 | **Approved** | Pure a11y; no behavior change otherwise. |
| 9 | **Approved** | Display-only. |
| 10 | **Approved (amended)** | `clear` returns the removed count; Settings refreshes stats after. Guard against the cache dir not existing. |

No rejections. Implementation order: 1, 2, 3, 10 (settings/account cluster), 4, 7
(backend), 5, 6, 8, 9 (frontend polish).
