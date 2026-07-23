# Optimization Cycle 03 — plan

Target version: **2607.3.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Real, explainable library health score

**Problem.** The Dashboard's health score is a placeholder (owned share + pending
actions) — it doesn't reflect anything the app actually measures, and the factor
grid under the orb doesn't explain the number.

**Change.** Deterministic score from real signals now in `/api/status`:
start at 100 and subtract weighted penalties — junk share
(`junk_flagged/owned`), upgrade share (`upgrades/owned`), and integration
completeness (from `/api/settings` connections). The factor list under the orb
names each deduction so the number is auditable at a glance. Pure frontend
arithmetic; no new endpoint.

**Files.** `Dashboard.tsx`, `HealthOrb.tsx` (only if props change).

## 2. Stop re-scoring the library every 8 seconds

**Problem.** `/api/status` now computes `junk.candidates(limit=10_000)` per call,
and the dashboard polls every 8 s — the whole library is re-scored dozens of
times a minute for a number that changes only on scan/keep/threshold writes.

**Change.** Small in-process TTL cache (30 s) around the two queue counts in
`routes_health._counts`, keyed by nothing (single instance), invalidated
explicitly on keep-override writes, threshold saves, and scan completion.
Counts stay exact within one poll interval of any change.

**Files.** `routes_health.py` (cache + invalidation hook), `routes_movies.py`
(keep endpoint invalidates), `routes_settings.py` (threshold save invalidates),
`ingest/pipeline.py` or `services/scanner.py` (scan finish invalidates), test.

## 3. Login rate limiting

**Problem.** `/api/auth/login` accepts unlimited attempts — an exposed instance
can be brute-forced.

**Change.** In-process sliding-window limiter: >5 failed attempts for the same
username within 60 s → 429 with `Retry-After`. Success clears the window.
In-memory only (single-process server), no new deps.

**Files.** `services/auth.py` or `routes_auth.py`, tests (limit trips, success
resets, other usernames unaffected).

## 4. Mid-session sign-out on 401

**Problem.** If the token dies mid-session (secret rotation, DB reset), every
page just silently fails — the app looks broken instead of asking to log in.

**Change.** The API client dispatches a `sift:unauthorized` window event on any
401; `AuthGate` listens and drops to the login screen (token cleared). Login
endpoints excluded (a wrong password is not a session death).

**Files.** `lib/api.ts`, `AuthGate.tsx`.

## 5. Table-view column sorting

**Problem.** In the Library's table view, sorting lives in a dropdown above the
table; clicking the column headers (the universal idiom) does nothing.

**Change.** Sortable column headers (Title, Year, Quality, Size, Added) that
sync with the existing `sort`/`order` params, with `aria-sort` and an arrow
glyph. The dropdown stays (it serves grid view).

**Files.** `Library.tsx`.

## 6. Junk reclaimable-space totals

**Problem.** The Junk queue never says what removal is worth — the whole point
of pruning is disk space.

**Change.** Header line shows the flagged set's total size ("~184 GB
reclaimable"); the multi-select action bar shows the size of the current
selection next to the count.

**Files.** `Junk.tsx` (client-side sum over already-loaded candidates).

## 7. Errors you can see — mutation toasts

**Problem.** Several mutations (`approve`, `keep`, `dismiss`, weight save)
swallow failures in `catch(() => …)` — the click just does nothing.

**Change.** A tiny shared toast (one at a time, auto-dismiss 4 s, polite
aria-live) + a `toastError(msg)` helper; wire it into the Junk decisions,
Missing dismiss, Must-Have dismiss, and Taste weight save catch paths. No
library.

**Files.** new `components/Toast.tsx`, `App.tsx` (mount), `Junk.tsx`,
`Missing.tsx`, `TasteProfile.tsx`.

## 8. Snapshot freshness on the Dashboard

**Problem.** The Dashboard never says how old the data is — "2 titles in the
snapshot" could be from five minutes or five weeks ago.

**Change.** Subhead gains "refreshed N ago" from `last_scan_finished_at`
(already in `/api/status`), and shows "snapshot may be stale" when the age
exceeds twice the configured rescan interval (when one is set).

**Files.** `Dashboard.tsx`.

## 9. Route-level code splitting

**Problem.** One 272 kB bundle: the login screen pays for the whole app.

**Change.** `React.lazy` per page (the eight routes) behind a `Suspense`
fallback matching the existing skeleton style. Shell/UI primitives stay in the
main chunk.

**Files.** `App.tsx`.

## 10. Multi-select accessibility

**Problem.** The Junk row checkboxes have no accessible names, and the sticky
action bar isn't announced as a group.

**Change.** Per-row `aria-label` ("Select <title>"), the action bar becomes a
`role="toolbar"` with an aria-label, and the selection count is a polite live
region.

**Files.** `Junk.tsx`.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | Score must stay deterministic + explainable — every deduction visible in the UI; no AI involvement. Integration completeness counts only *unconfigured* services (an outage is not the owner's fault). |
| 2 | **Approved (amended)** | Cache must be invalidated on **all three** write paths (keep, thresholds, scan finish), not just TTL-expired — a user who flags Keep must see the count drop on the next poll. Keep the TTL as a backstop, not the mechanism. |
| 3 | **Approved (amended)** | Key the window by username only (the server may sit behind a proxy where client IPs collapse); lock the *account*, not the address. Fixed 60 s window, no exponential state to leak memory. |
| 4 | **Approved** | Event-based; no redirect loops possible (login calls excluded). |
| 5 | **Approved** | Reuses existing query params; no API change. |
| 6 | **Approved** | Client-side sum only; no new endpoint. |
| 7 | **Approved (amended)** | One toast at a time, error-only (no success spam — the UI already reflects success by state change). |
| 8 | **Approved** | Read-only presentation of existing data. |
| 9 | **Approved (amended)** | Suspense fallback must respect reduced-motion (reuse the existing skeleton, which already does). Verify chunk count doesn't explode poster/vendor caching. |
| 10 | **Approved** | Attributes/semantics only. |

No rejections.
