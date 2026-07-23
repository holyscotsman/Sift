# Optimization Cycle 05 — plan

Target version: **2607.5.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Error boundary — one crashed page ≠ a dead app

**Problem.** There is no React error boundary anywhere: a render error on any
page white-screens the whole app with nothing but the console to explain it.

**Change.** An `ErrorBoundary` component wrapping the routed outlet (inside the
shell, so nav/header survive) with a friendly panel — what happened, a "Try
again" (reset boundary) and a "Reload" button. Route changes reset it.

**Files.** new `components/ErrorBoundary.tsx`, `AppShell.tsx`.

## 2. Choose where Radarr adds go

**Problem.** Add-to-Radarr silently uses the *first* root folder and *first*
quality profile Radarr returns — owners with multiple folders (4K vs HD, kids)
or profiles get whatever sorts first, with no way to change it.

**Change.** `GET /api/radarr/options` proxies Radarr's root folders + quality
profiles (existing client methods). Settings › Autonomy gains two dropdowns,
persisted via the config store; `radarr_add.resolve_add_options` prefers the
saved values (falling back to first-of-each when unset or no longer present).

**Files.** `routes_settings.py` (or actions routes), `services/config_store.py`
(two new radarr keys), `services/radarr_add.py`, `Settings.tsx`, `api.ts`,
types, tests.

## 3. Export the current library view as CSV

**Problem.** The snapshot is a real inventory (title/year/quality/size/watch
state) but there's no way to get it out — spreadshee​t questions ("what am I
storing in SDTV?") force screenshots.

**Change.** `GET /api/movies.csv` accepting the same filters/sort as
`/api/movies`, streaming `title,year,library_section,quality,file_size_gb,
in_plex,monitored,cutoff_unmet`. Library header gains "Export CSV" linking to
it with the current query (token via query param, as posters already do).

**Files.** `routes_movies.py`, `Library.tsx`, test.

## 4. Mobile pass at 375 px

**Problem.** The layout is desktop-first; at phone width the header search
competes with the logo, and paddings/cluster columns waste space. Never
audited.

**Change.** Screenshot-audit the main screens at 375×812, then fix what it
shows — expected: header wraps (search full-width on its own row), instrument
cluster stacks, table view hides more columns, junk action bar wraps cleanly.
Fixes stay in Tailwind responsive classes; no redesign.

**Files.** `Header.tsx`, `Dashboard.tsx` + whatever the audit reveals.

## 5. Grid tiles stop re-rendering on scroll

**Problem.** Library/Missing grids re-render every existing tile each time an
infinite-scroll page appends (new array → new element per item).

**Change.** `React.memo` on `GridTile`, the Library table row, and the shared
`Poster` (props are primitives, so default shallow compare is correct).

**Files.** `Library.tsx`, `ui.tsx`.

## 6. Ask answers get readable structure

**Problem.** Model answers arrive as a plain `whitespace-pre-wrap` blob —
lists/numbered steps (which models love) read as a wall.

**Change.** A tiny hand-rolled formatter (no dependency): split paragraphs,
render `- ` / `* ` / `1. ` runs as real lists, `**bold**` spans. Nothing else —
not a markdown engine.

**Files.** `Ask.tsx` (or a small `lib/format.tsx`), unit-testable pure
function.

## 7. Fill a collection in one click

**Problem.** Collection gaps list each missing title with its own Add button —
completing a 6-film collection is six clicks.

**Change.** Each gap section gains "Add all missing (N)" which walks the
existing per-title add action (sequential, same staging/dry-run semantics),
reporting per-title results. No new backend.

**Files.** `Missing.tsx`.

## 8. Warm the poster cache after a scan

**Problem.** The first Library visit after a scan fetches every poster
cold — a page of spinners/gradients on the screen that should feel "done".

**Change.** When a scan completes, warm the cache for the first grid page
(36 in-Plex titles by title order) in the background — bounded, best-effort,
failures ignored.

**Files.** `ingest/pipeline.py` or `services/scanner.py` (post-completion
hook), `services/posters.py` (reuse fetch path), test for the bound.

## 9. Login remembers who you are

**Problem.** The login form starts empty every time even though the username
is not a secret and rarely changes.

**Change.** Successful login stores the username (localStorage, never the
password); the form prefills it and focuses the password field instead.

**Files.** `AuthGate.tsx`.

## 10. Skip-to-content + labeled landmarks

**Problem.** Keyboard users tab through the whole header/nav on every page;
the app has no skip link and unlabeled landmarks.

**Change.** A visually-hidden-until-focused "Skip to content" link as the first
focusable element, `<main id="content">`, `aria-label`s on the nav and header
search landmark.

**Files.** `AppShell.tsx`, `TopNav.tsx`, `global.css` (focus style).

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | Boundary must reset on route change (a crash on one page must not brick the others) and must not swallow errors in dev — rethrow to console. |
| 2 | **Approved (amended)** | Saved ids/paths must be validated against what Radarr currently reports at *use* time — a deleted profile falls back to first-of-each rather than failing the add. Secrets stay out of the new endpoint (ids/paths/names only). |
| 3 | **Approved (amended)** | Stream, don't buffer (a 10k-row library shouldn't build one giant string); reuse the exact filter builder from /api/movies so the export always matches the visible set; cap at 20k rows. |
| 4 | **Approved** | Audit-driven; class-level changes only. |
| 5 | **Approved (amended)** | Memo props must actually be primitives — pass tmdb_id/title/year rather than the movie object where feasible, or accept the object but ensure the parent doesn't rebuild items each render (it appends). Verify with the React profiler once. |
| 6 | **Approved (amended)** | Formatter is a pure function with unit tests; unknown syntax must render as literal text (never dropped). No dependency. |
| 7 | **Approved (amended)** | Sequential adds with progress ("3/6…"); a failure stops the walk and reports which title failed. Add is autonomous-tier (staged under dry-run) — unchanged semantics. |
| 8 | **Approved (amended)** | Strictly bounded (36), fire-and-forget, and only on COMPLETED — an interrupted scan must not kick off network work. Skipped when TMDB is unconfigured. |
| 9 | **Approved** | Username only; never the password. |
| 10 | **Approved** | Standard a11y furniture. |

No rejections.
