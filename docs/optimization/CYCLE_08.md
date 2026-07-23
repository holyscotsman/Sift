# Optimization Cycle 08 — plan

Target version: **2607.8.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Decisions restore — the other half of the backup

**Problem.** Cycle 7 shipped the decisions *export*; after a redeploy on
ephemeral storage there is still no way to put the judgment back.

**Change.** `POST /api/import/decisions` accepts the exported JSON and applies
it in two explicit steps: a **preview** response first (`dry_run=true`, the
default — "would set N keep-overrides (M unknown titles skipped), re-dismiss K
must-haves, restore thresholds"), then the real apply on `dry_run=false`.
Keep-overrides apply only to tmdb ids present in the snapshot; unknown ids are
counted and skipped, never invented. Dismissals upsert must-have rows to
`dismissed`. Thresholds go through the existing validated store. Settings ›
Storage gains "Restore from backup" (file picker → preview → confirm).

**Files.** new route in `routes_export.py` (or a sibling), `Settings.tsx`,
`api.ts`, types, tests.

## 2. Poster cache stops growing forever

**Problem.** The poster cache has stats and a manual clear but no ceiling — a
big library on a small disk fills it poster by poster, forever.

**Change.** A size cap (default 500 MB, constant) enforced after each write:
when over cap, oldest files (mtime) are evicted until under. Settings ›
Storage shows "capped at 500 MB".

**Files.** `services/posters.py`, test (writes past the cap evict oldest,
newest survives).

## 3. Filter the Library by Plex section

**Problem.** The API has supported `section=` since Phase 0; the UI never
exposed it — owners with Movies / Documentaries / Anime sections can't slice.

**Change.** A section dropdown next to the sort control, populated from a new
tiny `GET /api/movies/sections` (distinct non-null sections). Hidden when
there's only one section. Feeds the existing `section` param (and the CSV
export inherits it for free).

**Files.** `routes_movies.py` (+9 lines), `Library.tsx`, `api.ts`, test.

## 4. The UI remembers how you like it

**Problem.** Library view (grid/table) and sort, and Junk's sort, reset on
every visit.

**Change.** Persist them to localStorage (`sift.library.view`, `.sort`,
`sift.junk.sort`) and hydrate on mount. Same pattern the prefs system already
uses.

**Files.** `Library.tsx`, `Junk.tsx`.

## 5. Esc cancels a thinking Ask

**Problem.** Cycle 7 added the Cancel button; the keyboard path still requires
the mouse.

**Change.** While a request is in flight, Escape aborts it (same code path as
the button). Ignored when not thinking.

**Files.** `Ask.tsx`.

## 6. Connection URLs get normalized

**Problem.** A pasted `radarr.local:7878/` or `http://plex.local:32400//`
fails opaquely — trailing slashes and missing schemes are the most common
setup mistake.

**Change.** On save/test, base URLs are normalized server-side: trim
whitespace and trailing slashes; prepend `http://` when no scheme is present.
Stored normalized so health checks and clients agree.

**Files.** `services/config_store.py` (normalize in `set_config` +
`apply_to_settings`), tests (scheme added, slashes trimmed, https preserved).

## 7. Dismissed must-haves can come back

**Problem.** Dismissing a must-have is forever — a mis-click or changed mind
has no path back, and the dismissed list is invisible.

**Change.** The Must-Have section gains "Dismissed (N)" — a collapsed strip of
dismissed titles with per-title "Restore" (`POST /api/musthave/{id}/restore`,
status back to `suggested`; the counts cache invalidates).

**Files.** `routes_musthave.py`, `Missing.tsx`, `api.ts`, test.

## 8. Ring gauges respect reduced motion

**Problem.** The gauge's stroke animation is a hardcoded `.6s` transition —
it ignores the reduce-motion preference the rest of the app honors.

**Change.** The transition duration rides the existing `--dur` custom property
(zeroed under reduced motion), matching every other animation.

**Files.** `ui.tsx`.

## 9. Backup files carry their date

**Problem.** Every backup downloads as `sift-decisions.json` — three backups
later nobody knows which is which.

**Change.** `Content-Disposition` filename includes the UTC date
(`sift-decisions-2026-07-23.json`); same for the CSV
(`sift-library-2026-07-23.csv`).

**Files.** `routes_export.py`, test asserts the pattern.

## 10. Loading states announce themselves

**Problem.** List skeletons are visual-only; screen-reader users get silence
while Library/Junk load.

**Change.** `aria-busy="true"` + a visually-hidden "Loading…" live region on
the Library, Junk, and Activity loading containers, cleared when content
lands.

**Files.** `Library.tsx`, `Junk.tsx`, `Activity.tsx`.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved (amended)** | This is a write surface: preview is the DEFAULT (`dry_run=true`); the apply requires the explicit flag from the confirm step. Input is validated field-by-field (unknown keys ignored, ids must be ints, thresholds via the existing validated setter); unknown tmdb ids are skipped and *counted*, never created. Restoring can only touch keep flags, must-have status, and thresholds — never files, never Radarr. Counts cache invalidates on apply. |
| 2 | **Approved (amended)** | Eviction must never delete a file written in the current request (evict strictly older-than-newest); cap is a module constant, not config, until someone asks. |
| 3 | **Approved** | Read-only endpoint; UI hidden when it offers nothing. |
| 4 | **Approved** | Preferences only; invalid stored values fall back to defaults. |
| 5 | **Approved** | Guarded so Esc still closes overlays when not thinking. |
| 6 | **Approved (amended)** | Never rewrite a URL that already has a scheme other than trimming; https stays https. Normalization applies to base_url fields only. |
| 7 | **Approved** | Reverses a UI-only decision; the suggestion re-enters the same gated pool it came from. |
| 8 | **Approved** | Token swap only. |
| 9 | **Approved** | Server clock, UTC, date only. |
| 10 | **Approved** | Additive attributes. |

No rejections.
