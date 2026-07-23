# Optimization Cycle 06 — plan

Target version: **2607.6.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Ask compare mode, made real

**Problem.** `AskRequest.mode` declares `"single" | "compare"` but the backend
never reads it and the UI never sends it — a dead feature flag. Owners running
tandem (Ollama + Anthropic) have no way to see the two models side by side.

**Change.** When `mode="compare"` and two distinct providers are configured,
`/api/ask` runs the same deterministic retrieval once and asks *both* providers
to phrase an answer, returning the second as `alternate` (provider/model/
latency labeled). The Ask page shows a "Compare" toggle only when tandem is
active, rendering the answers side by side. Retrieval stays deterministic; the
LLMs still only phrase — advisory rules unchanged. Single mode untouched.

**Files.** `routes_ask.py` / `ai/ask.py` (wherever the ask flow lives),
`schemas.py` (`alternate`), `Ask.tsx`, types, tests (compare returns two
labeled answers; single unchanged; compare degrades to single when only one
provider works).

## 2. Activity links to the movie

**Problem.** Activity shows "#603" as inert text — investigating an action
means going to the Library and searching by hand.

**Change.** The movie id chip becomes a button that opens the movie drawer
(same `useDrawer` flow as everywhere else), with the title looked up lazily by
the drawer itself.

**Files.** `Activity.tsx`.

## 3. Scan rows expand to their receipts

**Problem.** The Activity scan list shows status/when/duration but the
per-phase checkpoints and stats (already in the payload) are invisible.

**Change.** Clicking a scan row toggles a compact detail: per-phase status
line and the run's stats keys, plus the error text for failed runs.

**Files.** `Activity.tsx`.

## 4. Decided junk rows get out of the way

**Problem.** After a Keep/removal decision the full-height row lingers,
burying the still-undecided queue.

**Change.** Decided rows collapse to a single-line strip — title + outcome
pill ("kept", "removal staged", "removed") — with the details gone. The
undecided queue stays full-size.

**Files.** `Junk.tsx` (Row already receives `decision`).

## 5. Junk sorts by score or by size

**Problem.** The queue is score-ordered only; a disk-space purge wants
biggest-first.

**Change.** A two-chip sort toggle (Score · Size) above the list, client-side
over the already-loaded candidates.

**Files.** `Junk.tsx`.

## 6. Recently added on the Dashboard

**Problem.** The dashboard says nothing about what just landed in the library
— the most common "did it work?" question after a download.

**Change.** A "Recently added" poster strip (6 titles, `added_at` desc, from
the existing `/api/movies` with sort params) with drawer click-through. Hidden
when empty.

**Files.** `Dashboard.tsx`.

## 7. A footer that says what's running

**Problem.** The version is invisible in the UI — bug reports can't say what
they're running, and the changelog is undiscoverable.

**Change.** A quiet shell footer: "Sift {version}" (from `/api/version`) +
a link to the repo changelog. One fetch, cached in state.

**Files.** `AppShell.tsx` (or a small Footer component), `api.ts` (version).

## 8. Search results show ownership

**Problem.** Global-search results don't say whether you own the title — the
one fact that decides what clicking it means.

**Change.** Each result row gains a small "In Plex" pill (green) or a muted
"Radarr" tag for monitored-but-not-owned; nothing for neither.

**Files.** `GlobalSearch.tsx`.

## 9. Slow requests get logged

**Problem.** A hosted instance has no visibility into which endpoints are slow
(the health cache came from guessing).

**Change.** ASGI-level timing in the existing middleware stack: requests
slower than 500 ms log `method path status duration_ms` at WARNING (never
bodies, never query strings — paths only).

**Files.** `main.py`, test (slow route logs, fast route doesn't).

## 10. Wizard connections get a live check ✓

**Problem.** In the setup wizard each service must be tested one by one; the
overall "am I ready?" state is implicit.

**Change.** The wizard's connection step gains a compact readiness line —
"2 of 4 connected" — computed from the per-service test results already held
in component state (no new endpoint, no auto-probing).

**Files.** `SetupWizard.tsx`.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | Compare must degrade gracefully: if the second provider fails/times out, return the first answer with a note — never fail the whole request. Both answers share ONE retrieval (same sources) so they're comparable. UI toggle hidden unless the server reports tandem. Bounded: same token budgets as single. |
| 2 | **Approved** | Reuses the drawer; no new data path. |
| 3 | **Approved** | Read-only reveal of already-fetched payload. |
| 4 | **Approved** | Presentation only; decisions unchanged. |
| 5 | **Approved** | Client-side sort; default stays score (the safety-relevant ordering). |
| 6 | **Approved (amended)** | Must not add a poll — one fetch on mount; hidden (not skeleton) when the library is empty. |
| 7 | **Approved** | Version is public within the app (the API already serves it unauthenticated). |
| 8 | **Approved** | Data already in the result payload. |
| 9 | **Approved (amended)** | Log path templates/paths WITHOUT query strings (tokens ride in query params for downloads/posters — they must never reach logs). |
| 10 | **Approved** | Derived from existing state; no auto-probe spam. |

No rejections.
