# Optimization Cycle 02 — plan

Target version: **2607.2.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only).

## 1. Dashboard attention cards

**Problem.** After setup the dashboard doesn't tell you what to do next; missing
integrations degrade features silently (no TMDB → no posters/must-haves).

**Change.** "Needs your attention" gains state-driven cards: no scan yet → Run
scan; TMDB not connected → link Settings › Connections ("posters, classification
and Must-Haves need it"); Tautulli not connected → engagement signals note; AI
not configured → Ask/review note; ephemeral_risk → the Postgres warning.
Data comes from `/api/settings` (already carries everything) + `/api/scan` list.

**Files.** `Dashboard.tsx` only.

## 2. Taste weights actually steer recommendations

**Problem.** The Taste Profile "Emphasis" sliders persist but nothing reads them —
a control that silently does nothing.

**Change.** `analysis/recommend.py` reads the profile weights: candidates sharing
the library's top genres get a bounded boost scaled by the **genre** slider;
candidates whose decade matches the library's dominant eras get one scaled by the
**era** slider (`multiplier = 1 + weight * overlap`, capped ≤ 1.5×). Needs genre
ids from TMDB discovery payloads (`genre_ids`) mapped against the library's top
genre names via a static TMDB genre-id map. Deterministic; tested with a
golden ordering case. TasteProfile copy updates to say weights steer
recommendations now.

**Files.** `analysis/recommend.py`, new `data/tmdb_genres.py` (id→name, factual),
`analysis/profile.py` (expose top genres/eras helper), `TasteProfile.tsx` copy,
tests.

## 3. Global search inline results

**Problem.** The header search only filters the Library page; finding one movie
takes a page load + scroll.

**Change.** Typing in the header search shows the top 5 title matches inline
(poster thumb, year); click opens the movie drawer directly; Enter still goes to
the Library filtered view. Debounced 250 ms; Esc closes.

**Files.** `GlobalSearch.tsx` (uses existing `/api/movies?q=&page_size=5`).

## 4. Ask suggestions from your library

**Problem.** The Ask suggestion chips are hardcoded (Nolan/sci-fi) and may match
nothing the user owns.

**Change.** Build chips from `/api/profile`: top genre → "What are my
highest-rated {genre} movies?"; top director → "Which {director} films do I
have?"; top era → "What do I have from the {era}?". Falls back to the static
list when the profile is empty.

**Files.** `Ask.tsx`.

## 5. Scan history

**Problem.** Past scans (incl. automatic ones) are invisible — no way to see when
the snapshot was last refreshed or whether autoscan works.

**Change.** Activity page gains a compact "Scans" section above the action
timeline: last 5 runs with status, relative start time, duration, and headline
stats (movies/in Plex). Uses the existing `GET /api/scan` list endpoint.

**Files.** `Activity.tsx`, `api.ts` (scanList), types.

## 6. Security headers

**Problem.** Responses carry no browser hardening headers.

**Change.** Middleware adding `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: same-origin` to every response.
(No CSP yet — the inline-styled SPA needs a considered policy; deferred.)

**Files.** `main.py`, test asserting headers present.

## 7. Empty states with a way forward

**Problem.** Empty states describe the void but offer no action.

**Change.** `EmptyState` gains an optional `action` slot; wire the big ones:
Library empty → "Run scan"; Junk empty → "Adjust scoring"; Activity empty →
"Open Junk"; Missing collection-gaps empty keeps its explanatory text.

**Files.** `ui.tsx`, `Library.tsx`, `Junk.tsx`, `Activity.tsx`.

## 8. Poster loading hints

**Problem.** Poster `<img>`s load eagerly and without dimensions (layout shift,
wasted bandwidth on long grids).

**Change.** The shared `Poster` component sets `loading="lazy"`,
`decoding="async"`; grid/tile call sites keep their aspect-ratio boxes (already
CLS-safe), so just the attributes.

**Files.** `ui.tsx`.

## 9. GZip responses

**Problem.** `/api/movies` pages and big JSON payloads ship uncompressed.

**Change.** `GZipMiddleware(minimum_size=1024)`.

**Files.** `main.py`, test asserting `content-encoding: gzip` for a large
response.

## 10. Dashboard flag counts

**Problem.** `/api/status` counts don't include the two queues users care about
(junk flagged, must-have picks), so the dashboard can't show them.

**Change.** `counts` gains `junk_flagged` (current candidates) and
`musthave_pending` (suggested rows); Dashboard "Needs your attention" links show
the numbers.

**Files.** `routes_health.py` (or wherever /api/status lives), `schemas.py`,
`Dashboard.tsx`, types, test.

---

## Change review — verdicts

| # | Verdict | Notes |
|---|---------|-------|
| 1 | **Approved** | Read-only state, links only. |
| 2 | **Approved (amended)** | Boost must be bounded (≤1.5×) and only ever *reorder* — the anchor/gate machinery (owned-exclusion, TMDB grounding) is untouched; a zeroed slider must reproduce today's ordering exactly (test pins this). |
| 3 | **Approved (amended)** | Cap at 5 results, debounce ≥250 ms, and abort stale requests (latest-wins) so fast typing can't interleave. |
| 4 | **Approved** | Falls back to static chips; no new endpoint. |
| 5 | **Approved** | Read-only; reuses existing endpoint. |
| 6 | **Approved (amended)** | X-Frame-Options DENY is safe (no embedding use-case); skip HSTS (Render terminates TLS; local HTTP must keep working). |
| 7 | **Approved** | Actions navigate or trigger existing flows only. |
| 8 | **Approved** | Attributes only. |
| 9 | **Approved** | Standard middleware; WS unaffected. |
| 10 | **Approved (amended)** | `junk_flagged` must reuse `junk.candidates` (respects keep-overrides/kids-guard) not a raw score count, so the number always matches the Junk page. |

No rejections.
