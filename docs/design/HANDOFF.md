# Handoff: Sift — AI-Native Media Library Console

## Overview

Sift is an AI-native companion for a home Plex + Radarr media server. It scans the library, scores every title against the household's taste profile, surfaces junk candidates for removal, fills collection gaps, and answers natural-language questions about the catalog. This bundle contains the full interactive prototype: all 8 primary screens plus a movie-detail drawer, a destructive-confirm modal, and a design-system reference sheet.

Two guiding principles are baked into every screen:

1. **Calm by default, powerful on demand.** Dense information is available on drill-down (expandable signal breakdowns, "Advanced / raw metadata" escape hatch, per-tab detail), but the default view stays uncluttered.
2. **Everything controllable.** No black-box automation — every AI decision has a rationale, thresholds are user-editable, and destructive actions are always approval-gated.

## About the Design Files

**`Sift.dc.html` is a design reference created in HTML — an interactive prototype showing intended look and behavior, not production code to ship.** It is authored in a proprietary streaming component format ("Design Component") and bundles markup plus a JavaScript logic class with all interactivity mocked in-browser.

The task is to **recreate these designs in the target codebase's existing environment** — most likely a React/TypeScript SPA fronting a backend that talks to Plex, Radarr, Tautulli, and TMDB, plus a local LLM (Ollama) and the Anthropic API. Use the target codebase's established patterns (component library, state management, routing, styling). If no environment exists yet, React + Vite + Tailwind (or similar) is a reasonable default for a self-hosted dashboard.

**Do not ship the HTML directly.** Its animation and 3D interactivity are illustrative; the important artifact is the **visual language, information architecture, interaction model, and copy**.

## Fidelity

**High-fidelity.** Final colors, typography, spacing, motion, and copy are locked. Recreate pixel-close using the target codebase's libraries.

Signature elements (note: the aesthetic is deliberately **minimalist** — restrained, calm, lots of negative space):

- A duotone cyan→magenta gradient identity (`#2ee6e6 → #e85cf5`), used **sparingly** — only the wordmark and the single primary "Run scan" CTA carry the gradient. Everything else uses a single flat accent (cyan) or muted accent-tint fills.
- Bricolage Grotesque for display/headings + large numerals; Hanken Grotesk for body; JetBrains Mono for metadata/diffs/URLs.
- Three live themes (Spatial Dark, Spatial Light, Neon) over a shared, **very soft** aurora backdrop (low-opacity blurred gradients that drift slowly; pausable).
- Frosted-glass floating chrome: a rounded floating header and a rounded floating top-nav bar, both detached from the screen edges.
- A rotating 3D "library-health orb" as the one signature dimensional moment — otherwise surfaces are flat, low-shadow glass panels.
- Subtle pointer-tracked tilt + specular sheen on primary cards/posters (~6° max; disabled under Reduce Motion).
- Pages are grouped into **unified panels with hairline dividers** rather than grids of separate bordered cards.

## Global Shell (every screen)

- **Floating header** (60px tall, `border-radius: 26px`, 14px margin from edges, frosted `--chrome` glass):
  - Wordmark: 28px gradient tile with a paper-airplane glyph + "Sift" (17px Bricolage, weight 800).
  - Global search (max 400px). Keyboard: press `/` anywhere to focus it; ArrowUp/Down move the highlighted result; Enter opens it; Escape closes. Dropdown shows up to 6 matches (mini gradient poster + title + year), with the active row tinted `--bg-2`.
  - Connection-health dots (Plex, Radarr, Tautulli, TMDB, Model): green=ok, amber=warn, red=offline; hover shows a tooltip with URL + status detail.
  - Density toggle (cycles comfortable/compact), Theme toggle (Dark→Light→Neon), an "Idle / Scanning N%" status pill (opens the scan panel), and the primary gradient **Run scan** CTA.
- **Floating top-nav bar** (below header, same margins/radius, solid `--bg-1`, `flex-wrap`): Dashboard · Library · Missing · Junk · Ask · Taste Profile · Activity · Settings — then a flex spacer — then Design System. Active pill = quiet `--accent-soft` fill with `--accent` text (no gradient, no glow). Inactive = ghost; hover fills to `--bg-2`. Junk and Missing carry small numeric count badges. **Navigation is a horizontal top bar — there is no left sidebar/dock.**
- **Aurora backdrop** (`position:absolute; z-index:0; pointer-events:none`): three heavily-blurred radial gradients at low opacity (~0.22–0.32) drifting on 26/33/30s loops. Pauses under Reduce Motion.
- **Per-page transition**: each screen fades/rises in on mount (`sift-fadeup`, ~280ms).
- **Scan panel** (opens on scan): ~312px floating card with a 3D radar (conic-gradient sweep on a rotated disc), a 0–100% counter, and a 6-phase checklist — Reading Plex library → Fetching Radarr catalog → Pulling Tautulli history → Enriching TMDB metadata → Rebuilding taste profile → Scoring library. Phase dots: idle → active (accent, pulsing) → done (keep-green check).

## Screens

### 1. Dashboard
Anchor screen. H1 "Dashboard" + subhead. The centerpiece is a single wide **instrument-cluster panel** (one rounded panel, internal hairline dividers between segments — *not* a grid of stat boxes):
- **Library health** (widest segment): a 96px rotating 3D orb (radial-gradient sphere, gentle float; de-glossed — no heavy glow) with the health score inside; eyebrow, "Excellent standing" title, "Good" pill, and four factor chips (Duplicates, Below rating floor, Unwatched > 2y, Collection gaps) with colored dots + values.
- **Owned movies**: 46px Bricolage numeral + a stacked color bar split by library section (Movies / Kids / 4K) with a legend.
- **Monitored / Missing / Junk**: three circular ring gauges (80px), each colored (accent / amber / coral) with the value inside and a caption.
- Segments are divided by 1px vertical `--line` rules. On viewports < 1024px the cluster reflows to a 2-column grid.
Below: **Needs your attention** (up to 3 pending junk rows with poster, reason, band pill, Review button), **Recent activity** (last 4 events), and **Quick actions**. The whole cluster and the quick-action cards respond to pointer tilt.

### 2. Library
- H1 + count subhead: **"Showing 1–24 of {N} scored · 1,284 indexed in Plex"** — the grid is **paginated** (24/page grid, 50/page table) with Prev / "Page X of Y" / Next controls; page resets to 1 when filters change. The prototype ships ~160 scored titles so pagination and scale are real.
- View toggle (Grid / Table). Saved-view chips (All / Kids only / 4K library / Unwatched / Top rated + "Save view"). Section segmented control + filter chips (Genre / Decade / Rating / Watched) with clearable active state and dropdown option menus. Table view adds a Columns toggle menu.
- Multi-select bar (accent-tinted): N selected + Monitor / Add to review queue / Clear.
- **Grid**: `repeat(auto-fill, minmax(158px,1fr))`, 2:3 gradient poster tiles (colored by per-movie hue), quality chip, monitored dot, title overlay; year · rating · section below. Strong tilt + sheen; poster contents parallax.
- **Table**: 50px rows (38px compact); columns checkbox · poster · Title · Year · Library · Quality · Rating · Plays · Size · Monitored; sortable headers; row click opens the drawer. **Mobile story**: secondary columns (Year, Quality, Plays, Size, Monitored) auto-hide below 1024px, leaving poster · Title · Library · Rating.
- **Loading skeleton**: while a scan runs, the grid shows shimmer placeholder tiles. **Empty state**: "No movies match these filters" + Clear filters.

### 3. Missing
- **Collection gaps** (labelled "Deterministic"): a single panel with one divided row per owned collection — owned posters (green-check badge) + dashed missing slots that show "Added auto" or an Add button.
- **Recommended for you** (labelled "AI"), sortable by Fit / Year: a single panel of divided rows — poster, title/meta, a fit-score ring (color by score), rationale sentence, and Add (gradient) / Dismiss. Empty state when all reviewed.

### 4. Junk (Removal queue)
- Header + subhead: "Sift never deletes on its own. Every removal below needs your approval." "Approve all (N)" when pending; an "All caught up" keep-green banner when nothing is pending.
- One unified panel; each candidate is a **divided row** (not a separate card): poster (tilt), title + quality/size chips, an amber **Kids-library guard** banner where applicable, band pill (Keep/Borderline/Junk) + score ring, and a rationale paragraph.
- **Signal breakdown** disclosure per row: External rating / Watch history / Redundancy / Your rating, each with value + weighted bar.
- Action row: pending → "Keep it" + "Approve removal"; decided → "Removed"/"Kept" pill + "Change decision".
- **Destructive-confirm modal**: junk-tinted icon, "Delete N file(s)?" + GB reclaimed, item list, "cannot be undone" warning, Cancel + "Delete permanently". Scale-up entry, fading backdrop.

### 5. Ask
- Model toggle: Local / Anthropic / Compare.
- Thread: right-aligned user bubbles; assistant replies **stream in word-by-word with a live caret**. Single-model replies show model + latency, the answer, movie chips (open the drawer), and a colored source-chip row. **Compare** shows two side-by-side panes (each with model, latency, optional cost, answer, movie chips, "Use this answer"), sources spanning both.
- After each completed answer, a **"Follow up" chip row** offers 2 contextual next questions (clicking one asks it immediately).
- Composer: rounded input, Enter to send (Shift+Enter newline), gradient send button. Empty state shows 3 suggestion chips.

### 6. Taste Profile
- 2-column layout. Left: Top genres (bars), Keywords & themes (weighted type cloud), Directors + Actors (bars), Eras (vertical bars). Right (sticky): "Emphasis" — 5 weight sliders (Genre/Director/Cast/Keywords/Era) with a live "you favor X" note. "Recompute profile" runs a ~2.2s progress then toasts.

### 7. Activity
- The trust surface. Filter chips (All / Adds / Unmonitors / Deletes / Scans with counts). A **vertical timeline** (gradient spine) of **borderless entries** (icon disc on the line, no card border): title + tier chip (Auto / Auto+Audit / Approval / System) + timestamp, a monospace **dry-run diff** block (`+` keep-green, `-` junk-red, `~` amber, else muted), and a "via {source}" footer.

### 8. Settings
- 220px tab rail + content. Each tab is **one unified panel with divided sections** (not stacks of separate cards):
  - **Connections**: divided rows per service — status dot + name + label + Test connection (spinner → resolves), Server URL + API key fields, and a warn/offline banner (amber/red) when a service isn't healthy.
  - **Models**: Providers (Local + Anthropic with on/off pill switches, online status), Routing mode (Route by task / Compare / Race-fallback), Embedding provider chips.
  - **Scoring & thresholds**: 4 sliders (Minimum vote count, Rating floor, Not-watched years, Recommendation fit cutoff) each with a live "would affect N titles" footnote.
  - **Autonomy**: 3 tiers — Add (Automatic), Unmonitor (Automatic + Audit), Delete (Approval required, lock icon, cannot be disabled).
  - **Appearance**: Theme picker (3 swatches), Accent color (6 swatches — Sift derives a matching duotone via +58° hue shift), Density, Reduce motion switch (pauses aurora/tilt/orb).

### Movie-detail drawer (over any screen)
560px, slides in from the right with a slight rotate-Y; backdrop fades. Color backdrop strip → fade; close button. **The poster tile is a drag-and-drop image slot keyed per movie (`poster-{movieId}`)** — drop a real poster and it persists across reloads (empty state falls back to the gradient). Title + meta; Library/Quality/Monitored chips; ratings grid (TMDB / IMDb / Your rating); **Sift score** card (band pill + rationale); Watch history + File blocks; collection strip (owned = accent-bordered/full, missing = dashed placeholders); **Advanced / raw metadata** disclosure → monospace JSON dump; sticky footer (Monitor/Unmonitor + Removal queue).

### Design System sheet
Color tokens across all 3 themes; type scale (Display / H1 / H2 / Body / Caption / Mono); component gallery (buttons, score badges, toggle + segmented control, loading skeleton, filter chips, health-orb miniature).

## Interactions & Behavior

- **Nav** = instant route switch; content fades in per page.
- **Tilt**: on `pointermove`, one rAF computes cursor offset and applies `perspective(900px) rotateY/rotateX` (max 11° for `data-tilt="strong"`, 6° otherwise) + `translateZ(8px)`; a `data-sheen` layer gets a cursor-following radial highlight (screen blend); `data-parallax="N"` children translate by `-offset*N`. Resets on `pointerleave`. All off under Reduce Motion.
- **Health orb**: gentle 7s float loop, no spinning sheen (minimalist); pauses under Reduce Motion.
- **Scan**: click → 0→100% over ~6.2s, phases advance proportionally; on completion a toast + auto-close.
- **Search**: `/` focuses; ArrowUp/Down + Enter navigate results; Escape closes.
- **Escape** closes (in priority) modal → drawer → scan panel → open menus → search.
- **Ask streaming**: after a thinking delay, the answer reveals ~2 words per 42ms with a caret; movie chips/sources/follow-ups appear once complete. Compare reveals both panes together.
- **Drawer/modal/toasts**: spring-eased mount (`cubic-bezier(.2,.8,.2,1)`), fading backdrops, 3.2s auto-dismiss toasts bottom-right.
- **Reduce Motion**: sets `--anim: paused` and zeroes the `--dur*` variables.

## State Management (suggested slices)

- **App**: route/page, theme, density, accent color, reduce-motion, `narrow` (viewport < 1024px).
- **Scan**: scanning, scanPct, scanPhase, scanPanelOpen.
- **Library**: view mode, section/genre/decade/rating/watched filters, saved view, sort key + direction, **page**, selected ids, column-visibility map.
- **Junk**: expanded ids, decisions map (`id → 'approved' | 'rejected'`).
- **Ask**: model mode, input, thread (messages; assistant messages carry `panes[]` for compare, `followups[]`), thinking flag, streaming flag + reveal counter.
- **Taste**: weights map, recomputing flag + pct.
- **Settings**: active tab, thresholds, provider on/off, routing mode, embedding provider, per-connection test state.
- **Global UI**: drawer movie id, drawer raw-json flag, modal (`null | {type,ids}`), toasts, search query/open/highlighted-index.

**Data fetching (production):** Plex (items + sections), Radarr (monitored movies, quality profiles, delete endpoint), Tautulli (watch history/last-played/completion), TMDB (posters, ratings, keywords, cast/crew), LLM providers (Ollama local + Anthropic; Compare fans out to both and returns a `panes[]` object).

## Design Tokens

### Colors — Dark (primary)
| Token | Value |
|---|---|
| `--bg-0` | `#070812` |
| `--bg-1` | `linear-gradient(158deg,#191c33,#0f1124)` (panel surface) |
| `--bg-1s` | `#141731` (solid fallback for inputs) |
| `--bg-2` | `#1b1f3c` |
| `--bg-3` | `#272c4e` |
| `--line` | `rgba(150,165,255,.11)` |
| `--line-2` | `rgba(150,165,255,.22)` |
| `--fg` / `--fg-2` / `--fg-3` | `#eef0ff` / `#9ea6d4` / `#6a7099` |
| `--accent` | `#2ee6e6` (cyan — the single working accent) |
| `--accent2` | `#e85cf5` (magenta, derived +58° hue) |
| `--grad` | `linear-gradient(120deg,#2ee6e6,#8a7bf0 52%,#e85cf5)` — wordmark + Run scan only |
| `--accent-fg` | `#04141a` |
| `--accent-soft` / `--accent-line` | `rgba(46,230,230,.16)` / `rgba(46,230,230,.44)` |
| `--keep` / `--borderline` / `--junk` | `#4be6a4` / `#ffc24a` / `#ff6b8a` (semantic only) |
| `--chrome` | `rgba(11,13,30,.66)` (glass panels) |

Light: `--bg-0 #eceef7`, `--bg-1 linear-gradient(158deg,#ffffff,#f2f4fc)`, `--fg #161a2e`, `--keep #12a15e`, `--junk #e0455e`, `--chrome rgba(255,255,255,.76)`, aurora alphas ~0.24–0.32.
Neon: `--bg-0 #04030c`, `--bg-1 linear-gradient(158deg,#141034,#0a0820)`, `--fg #f2ecff`, `--junk #ff5c8f`, brighter aurora, slightly stronger glow.

### Radius / spacing
`--r-sm 9` · `--r-md 12` · `--r-lg 18` · `--r-xl 26` · `--r-pill 999`. `--card-pad` 22 (comfortable) / 15 (compact). `--gap` 18 / 12. `--row-h` 50 / 38. Page content: `max-width:1320px; padding:32px 40px 64px`.

### Typography
`--display` Bricolage Grotesque (H1/H2/H3 + all large numerals) · `--sans` Hanken Grotesk (body) · `--mono` JetBrains Mono (URLs, keys, diffs, raw JSON). Scale: Display 40–46 / H1 28–30 / H2 15–16 / Body 14 / Caption 11–12 (uppercase, tracked) / Mono 11.5–13.

### Shadows / effects (minimalist — kept soft)
- `--elev`: `inset 0 1px 0 rgba(255,255,255,.04), 0 16px 38px -30px rgba(0,0,0,.65)` — panels.
- `--shadow-1`: `0 2px 8px -4px rgba(0,0,0,.4)`.
- `--shadow-2`: `0 26px 60px -34px rgba(0,0,0,.78), 0 6px 18px -14px rgba(0,0,0,.5)` — modals/drawer.
- `--glow`: `0 0 20px -6px rgba(46,230,230,.32)` — the one primary CTA only.

### Motion
`--dur-fast` 160ms · `--dur` 280ms · `--dur-slow` 460ms. Keyframes: `sift-fadeup`, `sift-drawer`, `sift-backdrop`, `sift-modal`, `sift-toast`, `sift-spin`, `sift-pulse`, `sift-float`, `sift-orbrot` (scan radar), `sift-radar`, `sift-shimmer`, and `sift-aurora-a/b/c`. A single `--anim: paused` on the root disables all ambient motion for Reduce Motion.

## Assets

- **Posters**: no bundled art. Grid/collection/drawer posters are 2-stop `linear-gradient(155deg, hsl(hue 44% 32%), hsl((hue+38) 40% 15%))` per-movie fallbacks. The **drawer poster is a real drag-and-drop `<image-slot>`** (see `image-slot.js`) keyed `poster-{movieId}`, persisted to a sidecar; in production, replace the fallback with real TMDB poster URLs and keep the gradient for missing art.
- **Icons**: hand-rolled inline SVGs (see the `ICONS` map in the logic class). Consider Lucide/Tabler in production; keep them simple and geometric.
- **Fonts** (Google Fonts): Bricolage Grotesque (variable 400–800), Hanken Grotesk (400–800), JetBrains Mono (400–600).

## Files
- `Sift.dc.html` — the interactive prototype (single file: template + logic class + mocked data). Open in a browser to walk the full flow: switch nav pills, run a scan, paginate the library, drop a poster in a movie drawer, approve a junk removal (with confirm modal), and ask a question in Compare mode.
- `image-slot.js` — the drag-and-drop image-slot web component used by the drawer poster. Copy it alongside the HTML if you open the prototype locally.

## Recreation notes
- **Componentize**: Shell (Header, TopNav, Aurora), Dashboard/InstrumentCluster + HealthOrb, Library (Grid, Table, Filters, Pager), Missing (CollectionPanel, RecList), Junk (QueueRow, ConfirmModal), Ask (Thread, ComparePane, Composer, streaming hook), Taste (charts + weight sliders), ActivityTimeline, Settings/* , MovieDrawer.
- **Extract the mock data** (`MOVIES`, `RECS`, `COLLECTIONS`, `JUNK`, `ACTIVITY`, taste arrays, `CONN`) into fixtures / MSW handlers while real integrations are built. Note `MOVIES` is procedurally expanded to ~160 rows for scale — replace with real Plex data.
- **`useTilt(ref, {strength})`** as one hook applied to any card; gate on `prefers-reduced-motion` + the in-app toggle.
- **Route pages** (React Router / TanStack Router) with real URLs so screens deep-link — the prototype uses one `page` state key.
- **Persist** theme, density, accent, weights, thresholds, junk decisions, saved views, and dropped posters to local storage; sync to the server for multi-device.
- **Accessibility**: keep the 2px accent focus rings; the `/`, arrow-key, and Escape handlers; WCAG AA over the (now very soft) aurora; honor `prefers-reduced-motion`.
