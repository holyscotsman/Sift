# Optimization Cycle 04 — plan

Target version: **2607.4.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Stop hammering dead hosts — health probe cache

**Problem.** `/api/health` (polled every 20 s by the dashboard) and
`/api/settings` each live-probe every service on every call. With an
unreachable host configured, that's a stream of timeout-bound requests doing
nothing but warming the log.

**Change.** In-process TTL cache (15 s) around `gather_health`, hung on
`AppState` like the counts cache; explicitly invalidated when connections are
saved or a connection test runs (so "Test" always probes live). The health
snapshot the UI polls stays at most one poll stale.

**Files.** `services/health.py` or a small cache type, `deps.py`,
`routes_health.py`, `routes_settings.py`, `routes_config.py` (invalidate on
save/test), test.

## 2. Pause polling in hidden tabs

**Problem.** `useAsync` pollers (status 8 s, health 20 s) keep firing while the
tab is hidden — wasted requests and battery all day long for a tab nobody is
looking at.

**Change.** The poll tick skips while `document.hidden`; a `visibilitychange`
listener refetches immediately when the tab becomes visible again (so the
screen is never stale when the user returns).

**Files.** `lib/hooks.ts`.

## 3. Infinite scroll without repeated aggregates

**Problem.** `/api/movies` recomputes `COUNT(*)` and `SUM(file_size)` over the
filtered set for *every* page of an infinite scroll — page 5 pays for totals
the client already has.

**Change.** Compute totals only for `page == 1`; later pages return the items
with `total`/`total_size` zero and the client keeps the page-1 values (it
already only *uses* them from page 1's replace-load).

**Files.** `routes_movies.py`, `Library.tsx` (keep totals when appending),
test.

## 4. Ring gauges that mean something

**Problem.** The dashboard's third segment: "Pending" gauges against itself
(always a full ring), "Watched" gauges watch *records* against titles.

**Change.** Monitored stays (share of catalog). Watched becomes distinct
watched titles / owned. Pending gauges pending actions against the actionable
queue total (junk_flagged + upgrades + pending), so the ring visibly drains as
the queue is worked.

**Files.** `Dashboard.tsx`.

## 5. Search that admits a miss

**Problem.** A global search with no matches shows nothing at all —
indistinguishable from "still typing" or "broken".

**Change.** When a completed query has zero hits, the dropdown shows a single
"No titles match “q” — Enter searches the Library page" row.

**Files.** `GlobalSearch.tsx`.

## 6. Failed scans get a Retry

**Problem.** When a scan fails, the panel says so — and offers nothing. The
user must know to go find the scan button again.

**Change.** The scan panel's failed state gains a "Retry scan" button (calls
the existing `start()`, which resumes from checkpoints server-side when
possible).

**Files.** `shell/ScanPanel.tsx` (uses existing `useScan().start`).

## 7. Keyboard shortcuts + help

**Problem.** Only `/` (search) and Esc exist; power users get no fast nav and
nothing documents what keys work.

**Change.** `g` then `d/l/m/j/a/t/s` navigates (dashboard, library, missing,
junk, ask, taste, settings); `?` opens a small shortcuts overlay (Esc closes).
All ignored while typing in an input. One shared hook + overlay component.

**Files.** new `lib/shortcuts.tsx` (hook + overlay), `AppShell.tsx` (mount).

## 8. Honest connection states in Settings

**Problem.** The Settings connection list shows ok/not-ok only — "you never set
this up" and "your configured server is down" look identical.

**Change.** Not-configured services render neutral ("Not set up") with a setup
nudge; configured-but-unreachable render as errors with the probe detail.
Mirrors the distinction the Dashboard already draws.

**Files.** `Settings.tsx` (connection list rendering only).

## 9. Ask stays in flow

**Problem.** After sending a question the input loses focus (button steals it),
so a follow-up needs a click; a long thread has no way back to a clean slate.

**Change.** Input keeps focus after send; a "New conversation" button appears
once a thread exists, clearing it and restoring the suggestion chips.

**Files.** `Ask.tsx`.

## 10. Activity that goes back further

**Problem.** Activity fetches the last 80 actions, full stop — older history is
unreachable from the UI even though the API takes a limit.

**Change.** A "Show more" button under the timeline grows the window
(80 → 240 → 480…) until the returned count stops growing, then disappears.

**Files.** `Activity.tsx`.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | Connection saves AND tests must invalidate (a freshly fixed URL must not show dead for 15 s); the *test* endpoint itself always probes live, never reads the cache. |
| 2 | **Approved (amended)** | Must refetch on visibility return, not just resume the timer — otherwise the user stares at data as old as their lunch break. |
| 3 | **Approved (amended)** | Client must not zero its header totals when appending pages (keep page-1 values); server keeps computing totals when `page == 1` so deep-links and refreshes stay correct. |
| 4 | **Approved** | Presentation-only arithmetic on existing counts. |
| 5 | **Approved** | Static row, no new fetches. |
| 6 | **Approved** | Reuses the existing start() path (which already resumes from checkpoints). |
| 7 | **Approved (amended)** | Chord state (`g` prefix) must time out (~1.5 s) and never fire while an input/textarea/select or the drawer's focus trap is active; `?` respects the same guard. |
| 8 | **Approved** | Rendering-only; reuses the detail strings the API already returns. |
| 9 | **Approved** | Focus management only; no API change. |
| 10 | **Approved (amended)** | Cap the growth at 960 to bound the payload; hide the button when the server returns fewer than requested. |

No rejections.
