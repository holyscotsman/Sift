# Optimization Cycle 07 — plan

Target version: **2607.7.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Scan panel shows what it's counting

**Problem.** The websocket already streams per-phase counts ("plex_items:
1,234") but the panel shows only a checklist — the most informative signal in
the pipeline is dropped on the floor.

**Change.** The active phase line shows its latest counts inline ("Reading the
Plex catalog · 1,234 items"); phases without counts show nothing extra.

**Files.** `lib/scan.tsx` (keep last counts per phase), `ScanPanel.tsx`.

## 2. Poster fallbacks say which film they are

**Problem.** The gradient placeholder is anonymous — a grid of failed posters
is a wall of colored rectangles.

**Change.** The fallback gains the title's first letter, centered, in the
existing display font. `Poster` takes an optional `label`; grid tiles, search
rows, and Missing poster cards pass the title. No label → today's plain
gradient.

**Files.** `ui.tsx`, call sites (`Library.tsx`, `GlobalSearch.tsx`,
`Missing.tsx`).

## 3. Decisions leave the instance — backup export

**Problem.** Keep-overrides, dismissed must-haves, and tuned thresholds are the
owner's accumulated judgment; on SQLite-with-ephemeral-disk hosting they are
one redeploy from gone, with no way to save them.

**Change.** `GET /api/export/decisions.json` — keep-override tmdb ids (+
titles), dismissed must-have tmdb ids (+ titles), stored thresholds, and a
version stamp — as a download (token via query param like the CSV). Settings ›
Storage gains "Download decisions backup". Export only this cycle; import is a
write surface that deserves its own review.

**Files.** `routes_export.py`, `Settings.tsx`, test.

## 4. Vendor chunk for long-term caching

**Problem.** React/router ship inside the main app chunk — every app change
invalidates ~140 kB of never-changing framework bytes.

**Change.** Vite `manualChunks`: `react`, `react-dom`, `react-router-dom` into
a `vendor` chunk. Framework updates are rare; the vendor chunk becomes
effectively immutable between dependency bumps.

**Files.** `vite.config.ts`.

## 5. Junk stops hiding its own size

**Problem.** The Junk page fetches 200 candidates and never says whether that
was all of them — `total` comes back and is ignored (a silent cap).

**Change.** When `total > items.length`, a line under the list: "Showing
{items.length} of {total} flagged titles" with a "Load all" button
(refetches with `limit=total`, bounded 1000).

**Files.** `Junk.tsx`.

## 6. Expand all signal breakdowns

**Problem.** Auditing the queue's scoring means clicking "Signal breakdown"
once per row.

**Change.** A "Show all breakdowns / Collapse all" toggle above the list that
fills/clears the existing `expanded` set.

**Files.** `Junk.tsx`.

## 7. Long curated lists fold up

**Problem.** A 50-title curated list renders 50 posters on page load, pushing
the sections below it far off screen.

**Change.** `ListSection` shows the first 12 with "Show all (N)" when longer;
collapsing restores. Same for collection-gap member strips left as-is (they're
naturally short).

**Files.** `Missing.tsx`.

## 8. Ask can be cancelled

**Problem.** A slow local model means staring at "Thinking…" with no way out —
the request runs to timeout even after the user has given up.

**Change.** `api.ask` accepts an `AbortSignal`; the thinking bubble gains a
Cancel button that aborts the fetch, removes the pending state, and restores
the input text. Compare mode inherits it for free (same request).

**Files.** `api.ts`, `Ask.tsx`.

## 9. Health dots go somewhere

**Problem.** The header's connection dots diagnose but don't lead anywhere —
fixing a red dot means finding Settings yourself.

**Change.** The dot group links to `/settings` (Connections), keeping the
per-dot tooltips.

**Files.** `HealthDots.tsx`.

## 10. Gauges get accessible names

**Problem.** `RingGauge` and `HealthOrb` are bare SVG — screen readers hear
nothing where sighted users see the dashboard's key numbers.

**Change.** `role="img"` + `aria-label` built from caption/value on RingGauge;
an aria-label ("Library health {score} of 100") on HealthOrb.

**Files.** `ui.tsx`, `HealthOrb.tsx`, call sites passing captions.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | Counts render must not allocate per frame — store last counts per phase in existing state updates, formatted on render only. |
| 2 | **Approved** | Optional prop; default unchanged. |
| 3 | **Approved (amended)** | Export only — no import endpoint this cycle (a restore endpoint writes state and needs its own gated review). Same query-param token auth pattern as the CSV; titles included so the file is human-readable. |
| 4 | **Approved** | Build config only; verify the chunk actually splits. |
| 5 | **Approved (amended)** | "Load all" bounded at 1000; the line appears only when the cap actually bit. |
| 6 | **Approved** | Reuses existing per-row expansion state. |
| 7 | **Approved** | Presentation only. |
| 8 | **Approved (amended)** | Abort must also clear the thinking state if the fetch already resolved (race); restoring the typed question must not duplicate the user bubble — drop the pending user message instead. |
| 9 | **Approved** | Navigation only. |
| 10 | **Approved** | Attributes only. |

No rejections.
