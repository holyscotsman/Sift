# Changelog

Versioning scheme: `YYMM.major.patch`.

## 2607.16.0 — Where the disk went, and the safest way to get it back

Sift could tell you whether a film deserved to be on the server. It could not
tell you where the space was going, and for TV it could not tell you anything at
all: every one of the sixteen tables was keyed on `Movie.tmdb_id`, and one line
in the Plex phase skipped any section that was not a movie section.

**Size is now measured in bytes per hour, against the library's own norms.**
Raw size is not a verdict — thirty gigabytes is unremarkable as a three-hour 4K
remux and absurd as a ninety-minute 1080p — so any rule phrased in gigabytes
flags the wrong files in both directions. Baselines are the median per
(resolution, codec) bucket measured from your own files, with spread taken as the
median absolute deviation rather than the standard deviation: the outliers are
what is being looked for, and a handful of remuxes drag a mean upward far enough
to hide behind it.

**The file detail this needs was already being downloaded and thrown away.**
`normalize_radarr_movie` opened `movieFile` to read the quality name and dropped
`mediaInfo`, `path` and `size` from the same dict; Plex's listing carries a
`Media`/`Part` block and the normalizer kept seven fields. The movie half of this
release costs no extra requests, only the parsing.

**Small files are judged by duration against the published runtime**, not by
size. Under a gigabyte describes three different situations, and the worst
mistake available was deleting a genuine short film for being short. A file that
stops after eight minutes of a two-hour feature is a sample or an unfinished
download and is free disk; a full-length file at a fraction of its peers' bitrate
is a bad rip that wants replacing, and is reported with *zero* reclaimable
because you keep using that disk until a better copy arrives; a 22-minute film in
a 400 MB file is simply correct. With no published runtime there is no verdict at
all.

**TV arrives whole.** Sonarr supplies the catalog and the files; Plex supplies
membership and every copy it can see, which is what makes a duplicated episode
findable — Sonarr tracks one file per episode, so a second copy on disk is
invisible to it. Season is the grain that matters, and air year is taken per
season from the episodes: Scrubs began in 2001 on SD video and ended in HD, so
one answer per show is wrong for every long-running series.

**Duplicate episodes exclude the two cases that look identical.** A single
S01E01-E02 file is identified by path rather than by the episodes pointing at it,
so it counts its disk once. Split parts are the dangerous one, because duration
cannot separate them — two halves of a sixty-minute episode and two copies of a
thirty-minute one are both two files of thirty minutes, and deleting the
"duplicate" loses half the episode. Plex already draws the distinction
structurally, so it is read rather than inferred.

**HD or SD is decided from three deterministic signals**: what the season's
master can deliver, how much the picture rewards pixels, and how attentively the
show is actually watched. That separates anime from SpongeBob and Severance from
Scrubs. Recognition is deliberately *not* consulted and a test pins that it never
is — it measures fame, and SpongeBob is one of the most recognised shows ever
made, so feeding it in inverts the decision. The bar is asymmetric: an upgrade
only costs disk and can be undone, so one signal justifies it; a downgrade
destroys picture that cannot be recovered without re-acquiring the show, so it
needs low demand, low or absent attention, and a known air year. Thin evidence
returns "not enough to say" rather than a guess.

**Everything lands in one queue, ordered by risk before size.** Five separate
reports leave you to work out which to act on first, and no one of them can
answer it. Findings carry a tier — nothing is lost, reversible, a judgement call
— and the ordering is the substance: sorted by size alone the list routinely puts
an irreversible downgrade above a duplicate copy that costs nothing to remove.
Most of the disk comes back at tier 0, before a single question of taste. The
planner takes a target and returns the cheapest way to reach it, cheapest
measured in regret, and says plainly when the library cannot reach it.

**Transcodes are gated as deletes are, and Sonarr is stopped from undoing them.**
Replacing a file with a lossier one is a delete spread over time, so the golden
guard generalises from "is this a delete" to "is this irreversible". Sift never
carries one out — it has no access to the media — so an approved job is claimed
by an agent on the media box, which polls because a hook would need that box
reachable from wherever Sift runs. Approval is checked at claim time rather than
trusted from job creation, a staged instance hands out nothing, and a reported
success must bring its output size and duration, because an unverifiable success
is how a failed encode gets swapped in for the real file. Every applied downgrade
writes the quality profile back to Sonarr: without that its next search fetches
the larger file straight back, which costs the picture and keeps the disk.

Storage is a new screen and is read-only. It ships before anything can act on a
finding, and shows the baselines it used, because these verdicts rest on the
claim that your library's own median describes it — worth checking against
reality before it drives a delete. It also surfaces `GET /api/duplicates`, which
the backend has served since 2607.14.0 with nothing on screen to show it.

341 tests, each new pin mutation-verified. The TV ingest pin counts *lookups*
rather than statements: the defect 2607.15.1 fixed was a SELECT per row, while
inserting new episodes genuinely requires writes and how a driver batches those
varies by dialect. Ten episodes and a hundred cost the same number of lookups,
and a rescan of a hundred costs six statements.

## 2607.15.1 — Fix the Plex phase stalling

Recording duplicate copies (2607.14.0) was written with a `session.merge()` per
film. Merge issues its own SELECT and flushes pending work on every call, so the
phase went from one statement per film to **four** — invisible on local SQLite,
crippling on a hosted database where each statement is a network round trip. A
few thousand films became minutes of pure latency and the scan looked hung on
"Reading Plex catalog".

Movies and copies are now preloaded in a handful of queries and matched in
memory, and stale copies are removed with a single batched DELETE instead of a
full table load filtered in Python.

Measured on 500 films: **4.0 statements per film → 0.01**. For a 4,000-film
library at 25 ms per round trip that is roughly seven minutes of latency reduced
to under a second.

A regression test pins the query count on a rescan, so the per-item shape cannot
come back unnoticed.

## 2607.15.0 — One branch, a published image, and a version you can see

Housekeeping that turned out to matter: the repository default branch was a
stale feature branch, and `DEPLOY.md` told you to point Render at it. Anything
merged to `main` therefore never reached a deploy following those instructions.

- **`DEPLOY.md` now says deploy from `main`**, and warns to check the branch on an
  existing service. That instruction was the cause, not a symptom.
- **The example Radarr hostname is now `radarr.example.com`.** A real one was
  committed, and the repository is public with GitHub Pages enabled — which makes
  it indexable rather than merely present.
- **`publish.yml`** builds the container on every push to `main` and pushes it to
  GHCR, tagged `latest` and the exact version. Free, no account, no secret — it
  authenticates with the token GitHub already provides. A host can then deploy a
  prebuilt image instead of building from source.
- **`docker-compose.yml`** runs Sift on your own machine. On the box already
  running Plex and Radarr this removes the whole class of hosted problems at
  once: nothing sleeps, there is no cold start, the database is a file on your
  disk, and Radarr never needs to face the internet.
- **Settings › Maintenance shows the running version** and whether a newer one is
  published, which is what makes the Update button meaningful — you can see
  whether there is anything to update *to*. The check is cached for an hour,
  bounded, and fails soft. A failed check reports "couldn't check", never "up to
  date": claiming currency you cannot verify is the only answer that misleads.
- Version comparison is numeric. `2607.9.0` sorts before `2607.14.0`, which a
  string compare gets backwards — it would have nagged an up-to-date instance
  forever.

## 2607.14.0 — Duplicates, and Restart/Update in the app

**Duplicate copies are visible for the first time.** Films are keyed by TMDB id,
so a library holding three rips of one title collapsed into a single row and only
the last Plex rating key survived — duplicates were invisible by construction,
because they were never recorded. A new `plex_copies` table stores one row per
Plex *item*. A new table rather than extra columns is deliberate: the schema is
built with `create_all`, which adds tables to an existing database but never
columns, so this deploys with no migration.

- `GET /api/duplicates` lists films held more than once, most-duplicated first,
  with the total number of copies that could go while keeping every film.
- Grouping is by TMDB id, never title — "The Fly" (1958/1986) are different
  films and a dozen releases are called "Godzilla".
- Copies Plex stops reporting are dropped, so tidying one up on disk stops it
  being recommended again.
- **Fixes a real data loss on the way.** Watch history is matched back by rating
  key, and only the surviving one was in the map — so plays recorded against any
  other copy were silently discarded, making a watched film read as never-played.
  Under the old scoring that counted toward removal.

**Restart and Update, in Settings › Maintenance.** Both hand control to the host,
because a web app cannot reliably restart or upgrade itself.

- **Restart** asks the process to exit; a managed host brings it back. On a bare
  local run nothing is watching, so the response says so instead of implying a
  restart that will not happen.
- **Update** pokes a deploy hook — a secret URL the host provides — and the host
  builds the latest code. Sift never pulls or executes anything itself. With no
  hook set it returns an actionable error rather than silently doing nothing.
- The hook is stored as a **secret**, encrypted at rest like an API key, since
  anyone holding it can trigger a deploy.
- Both buttons arm on the first click and act on the second.

## 2607.13.0 — Recognition, not reviews, decides what goes

The removal score measured **quality**, and used vote counts only to decide how
much to trust a rating. That made fame a liability — 3,200 people agreeing a film
is bad pushed it *further* toward deletion — and obscurity a shield, because a
handful of votes dragged a mediocre film up toward the neutral prior. Run the
owner's own examples through the old code and it proposed deleting Animal Farm
and Battlefield Earth while keeping an unknown 1976 indie.

- **New `analysis/recognition.py`.** Scores a title's public footprint, not its
  merit: vote volume judged **against same-decade peers** (TMDB's audience skews
  modern, so a global comparison quietly condemns the entire classics wall), plus
  theatrical run, studio-scale budget, franchise, and cast. Rating is not an input.
- **Curated-list membership floors the score.** Without it, culling the obscure
  would delete exactly the Criterion and cult titles the Missing page tells you to
  acquire — they look identical to forgotten straight-to-video on votes alone.
- **Franchise fame is gated on a theatrical release**, so a fourth-tier
  direct-to-video spin-off can't inherit a famous name it never earned.
- **Never-played no longer condemns.** It contributed 0.85 of a possible 1.0
  toward junk, so an unwatched *Schindler's List* scored the same as genuine
  dross — and most of a well-stocked shelf is unwatched by definition. Watching a
  film can now save it; not watching one can never remove it.
- **Rating demoted to a tiebreaker** (weight 1.0 → 0.2) between titles that are
  equally unrecognised. It can no longer outvote recognition.
- Titles TMDB hasn't enriched yet fall back to the old composition rather than
  being scored as unrecognised, so a partial scan can't propose deleting the
  library.
- The Junk row now shows the recognition tier, because "obscure" is the actual
  reason a title is listed.

Also in this release:

- **Overseerr 409 is a success, not an error.** Overseerr answers 409 when it
  already holds a request; a blanket `except` turned that into "couldn't reach
  Overseerr", recorded no action, and left the button stuck on something no retry
  could fix — so the title never left Missing either. It's now recorded as a real
  request ("Already requested ✓"). A rejected API key gets its own message instead
  of reading like a network fault.
- **`keepalive.yml`** — an optional scheduled workflow that pings the public
  `/api/version` so a free Render instance stops cold-starting. Render spins down
  on absent *inbound HTTP*; Sift's own timers can't prevent it. Off unless a
  `SIFT_URL` repository variable is set.

## 2607.12.0 — Requests stick, dead services don't stall the scan

- **Requested titles leave Missing.** Missing diffed the canon against Plex only,
  so a film you'd just requested sat there until it finished downloading — days
  of looking un-actioned, and easy to request twice. Anything with an add that
  actually left Sift is now filtered out, with the count shown ("N already
  requested and on the way") so nothing silently disappears. A **staged**
  (dry-run) add reached nothing, so it correctly stays listed.
- **Request all on Missing.** Requests the titles currently shown rather than the
  whole canon, and arms on the first click so a stray tap can't fire hundreds of
  requests at Overseerr.
- **Scan pre-flight.** Every configured service is probed first, with a hard
  15-second bound. Anything that doesn't answer is dropped for that run and its
  phase becomes a no-op. Previously a saved-but-unreachable service — Tautulli
  being the usual culprit — raised inside its phase and interrupted the whole
  scan, so a perfectly healthy Radarr never got read. The phase names what it
  skipped. It re-runs on resume, because reachability isn't something a previous
  run's checkpoint can vouch for.
- **The AI phase can no longer park a scan.** It reviews candidates one at a time
  against a live provider with no bound, so fifty of them could sit on "AI
  analysis" for minutes. It now has a two-minute budget and keeps whatever notes
  it produced, and reports *why* it produced nothing — no provider configured, a
  failure, or the budget — instead of logging at info and returning silence.

## 2607.10.1 — Persistence, documented properly

- **`DEPLOY.md` now walks through both persistence routes** step by step instead of
  presenting Postgres as the only real option with a one-line footnote. Route A is
  a Render Disk (keeps SQLite; needs a paid instance, but also persists the
  thumbnail cache and gets daily disk snapshots); Route B is free hosted Postgres.
  Both are spelled out click by click, with the trade-offs and the common
  mistakes — `SIFT_DATABASE__URL` silently overriding the disk path, pooled vs
  plain Neon connection strings.
- **Says what's actually at stake.** The old wording implied only the login and
  service keys were lost on redeploy. It's the whole database: every movie, score,
  rating, watch-history row, collection, and keep/remove decision too.
- **Fixed: the ephemeral-disk warning no longer cries wolf.** It fired on
  SQLite + Render regardless of where the file lived, so anyone who fixed
  persistence with a mounted volume kept being told their data resets on redeploy.
  A SQLite path that is absolute and outside the app directory is now recognised as
  a mounted volume (`DatabaseConfig.on_mounted_volume`).

## 2607.10.0 — Service keys encrypted at rest

Groundwork for running Sift on a **persistent** database. Until now the fix for
"my login and keys reset on every redeploy" (point `SIFT_DATABASE__URL` at a free
Postgres) had a catch: connection secrets were stored in plaintext, which is
tolerable on a throwaway SQLite file and not tolerable in a cloud database that
keeps backups. Now they're sealed before they're written.

- **Encryption at rest for stored credentials.** Plex tokens and Radarr / TMDB /
  Overseerr / Anthropic keys entered in the wizard or Settings are encrypted
  (Fernet) before they reach the database. Non-secret fields (base URLs, models,
  language) stay readable. New `services/secretbox.py`.
- **No new setup step.** Key material is resolved from `SIFT_SECRET_KEY` if set,
  otherwise the existing `SIFT_SERVER__API_TOKEN` — so an instance that already
  has an access token gets this for free. `render.yaml` now generates a
  `SIFT_SECRET_KEY` for new blueprint deploys. **The key never lives in the
  database**, so a leaked connection string yields ciphertext.
- **Existing databases upgrade themselves.** Secrets already stored in plaintext
  are sealed in place on the next boot — idempotent, and a no-op when no key
  material is available.
- **Unchanged without key material.** With no token and no explicit key (a plain
  local SQLite install), values are stored exactly as before. Nothing to migrate.
- **Losing the key is not destructive.** An unreadable secret reports as
  not-configured — re-enter it in Settings — rather than crashing the app, and an
  unrelated save can never overwrite a secret this instance can't currently read.
- **The session signing secret is sealed too** — and this one is load-bearing. In
  the clear it sits in the same table, and it alone is enough to forge a valid
  admin session from a database dump; the attacker then has the running app
  decrypt every other credential for them. Encrypting the connection keys while
  leaving it readable would have been theatre. Verified by building the exploit
  and confirming the forged token is now rejected.
- **You cannot be locked out by a key change.** An unreadable signing secret
  signs everyone out, but `login` verifies against the password hash (which is
  independent) and mints a replacement, so access always recovers.
- **Adding a key later is safe.** Decryption tries the primary key and then the
  fallback, so an instance sealed under the access token keeps working when a
  `SIFT_SECRET_KEY` appears (as Render generates on a blueprint sync); the boot
  upgrade then re-seals under the new primary. Without this, following the
  documented path would have orphaned every stored credential.
- **Visible, not assumed.** `/api/settings` reports `secrets_encrypted`; Settings ›
  Account confirms it, and warns when a persistent database is paired with
  unencrypted secrets.
- Docs: `DEPLOY.md` gains the encryption note and a key-rotation section, and is
  explicit that this protects data *at rest* — backups, replicas, a leaked
  connection string — not the running instance.
- New dependency: `cryptography`.

Known limitation, unchanged by this release: an attacker who is already
authenticated (has your access token or a live session) can point a service's
`base_url` at a host they control and have Sift send that service's credential
there. That predates this change and is tracked separately; encryption at rest
does not address it.

## 2607.9.0 — Missing redesign, Overseerr, theatrical junk rules

Owner-requested batch:

- **Missing, rebuilt.** The backend now keeps a private canon of theatrical-scale
  films worth owning — TMDB's top-rated chart, a revenue-sorted blockbuster
  sweep, the curated lists (cult / IMDb top / criterion), and gated curator
  picks. The Missing page shows only the difference against the **Plex library**
  (Radarr is deliberately ignored) as a poster grid with per-title Request
  buttons and a "Refresh catalog" action. The canon itself stays backend-only.
- **Collections is its own page** (nav item between Missing and Junk) with the
  same gap view as before plus one-click "Request all missing".
- **Overseerr integration.** New connection (Settings › Connections + wizard +
  health dot). When configured, every add-request routes through Overseerr's
  approval pipeline; otherwise it falls back to a direct Radarr add. The server
  dry-run floor applies to both paths, and every request is recorded in the
  audit trail with its route.
- **Junk keeps theatrical-scale releases.** The protection now covers US
  theatrical runs, major-studio releases (Disney, Amazon, Netflix, …) even when
  streaming-only, and studio-scale budgets (≥ $20M) — famously bad big films are
  kept on purpose. Junk stays aimed at low-budget, independent, and non-theatrical
  international titles. Takes full effect after the next scan re-enriches. All
  flagged candidates now start **selected for removal** by default (nothing is
  sent until Approve + confirm), and every row carries an **IMDb ↗** link.
- **Thumbnails fixed.** Radarr-relative poster paths (/MediaCover/…) are no
  longer stored, stored-but-dead poster URLs now fall back to a TMDB lookup and
  heal themselves, so artwork resolves for every title with TMDB connected.
- **Header polish.** A bigger, sharper Sift wordmark, and the previously-dead
  three-line button is now a real menu (row spacing, theme, keyboard shortcuts,
  changelog, sign out). Taste-graph recommendations moved to the Taste Profile
  page.
- **Dependency security:** react-router upgraded v6 → v7.18 to clear
  CVE-2025-68470-adjacent advisories; `npm audit` clean again.

## 2607.8.0 — Optimization Cycle 08

Ten reviewed changes (plan: `docs/optimization/CYCLE_08.md`, log:
`OPTIMIZATION_CHANGELOG.md`): decisions restore with preview-by-default apply
flow, a 500 MB poster-cache ceiling with oldest-first eviction, a Library
section filter, persisted view/sort preferences, Esc-cancellable Ask,
connection-URL normalization (scheme + trailing slashes), restorable dismissed
must-haves, reduced-motion-aware gauges, dated backup filenames, and announced
loading states.

## 2607.7.0 — Optimization Cycle 07

Ten reviewed changes (plan: `docs/optimization/CYCLE_07.md`, log:
`OPTIMIZATION_CHANGELOG.md`): live per-phase scan counts in the panel, poster
fallbacks labeled with the title's initial, a decisions backup download
(keep-overrides + dismissals + thresholds), a vendor chunk (app bundle 222 kB →
59 kB), junk cap disclosure with bounded Load-all, expand-all signal
breakdowns, folding curated lists, cancellable Ask requests, health dots
linking to Settings, and accessible gauge labels.

## 2607.6.0 — Optimization Cycle 06

Ten reviewed changes (plan: `docs/optimization/CYCLE_06.md`, log:
`OPTIMIZATION_CHANGELOG.md`): real Ask compare mode (both tandem providers
phrase one retrieval, side by side, graceful degradation), Activity movie-id
drawer links + expandable scan receipts, collapsed decided junk rows, junk
score/size sort, a recently-added dashboard strip, a version footer, ownership
pills in global search, slow-request logging (paths only — tokens never reach
logs), and a wizard readiness line.

## 2607.5.0 — Optimization Cycle 05

Ten reviewed changes (plan: `docs/optimization/CYCLE_05.md`, log:
`OPTIMIZATION_CHANGELOG.md`): route-level error boundary, chooseable Radarr add
defaults (root folder + quality profile with stale-safe fallback), streaming
CSV export of the filtered library, 375 px mobile fixes (search row, no CTA
wrap), memoized grid tiles/posters, a tiny Ask answer formatter, one-click
collection fill with progress, bounded poster warm-up after completed scans,
username prefill at login, and skip-to-content + labeled landmarks.

## 2607.4.0 — Optimization Cycle 04

Ten reviewed changes (plan: `docs/optimization/CYCLE_04.md`, log:
`OPTIMIZATION_CHANGELOG.md`): cached health sweep (774 ms → 10 ms polls) with
save/test invalidation, visibility-aware polling, page-1-only list aggregates,
meaningful ring gauges (new `watched_titles` count), a search no-match row,
scan-failure Retry, `g`-chord keyboard navigation + `?` shortcuts overlay,
honest not-set-up vs unreachable connection states, Ask focus retention +
New conversation, and a growing bounded Activity window.

## 2607.3.0 — Optimization Cycle 03

Ten reviewed changes (plan: `docs/optimization/CYCLE_03.md`, log:
`OPTIMIZATION_CHANGELOG.md`): auditable health score with named deductions,
cached status queue counts with exact write-path invalidation, login
brute-force guard (per-account 429 + Retry-After), mid-session sign-out on dead
tokens, sortable table columns (+ Size column), junk reclaimable-disk totals,
shared error toasts on failed mutations, snapshot freshness + stale hint,
route-level code splitting (272 kB → 216 kB main bundle), and multi-select
toolbar accessibility.

## 2607.2.0 — Optimization Cycle 02

Ten reviewed changes (plan: `docs/optimization/CYCLE_02.md`, log:
`OPTIMIZATION_CHANGELOG.md`): state-driven dashboard attention cards with live
junk/must-have queue counts, taste-profile weights that actually steer
recommendations (bounded reorder, zero-weight equivalence test-pinned), inline
global-search results with poster thumbs + latest-wins fetches, Ask suggestion
chips built from the library profile, scan history on Activity, security headers
(nosniff / DENY / same-origin referrer), empty states with a next-step action,
async poster decoding, gzip for large JSON responses, and `junk_flagged` /
`musthave_pending` status counts that always match their pages.

## 2607.1.0 — Optimization Cycle 01

Ten reviewed changes (plan: `docs/optimization/CYCLE_01.md`, log:
`OPTIMIZATION_CHANGELOG.md`): password-manager-friendly login + ephemeral-host
warning, in-place password change, per-service "clear saved values", automatic
rescans (6/12/24h), Junk multi-select, Library title/disk totals, ~4× faster
Must-Have validation, drawer Esc/focus accessibility, readable Activity
(relative times, collapsed payloads), poster-cache stats + clear. Security pass:
new endpoints gated, bandit ruleset + npm audit clean, narrowing asserts replaced
with explicit raises.

## Unreleased

### Added — refined AI engine, Must-Have catalog, and onboarding flow
- **AI engine modes** (Settings › Connections): **Tandem** (local Ollama drafts,
  Anthropic refines — default), **Claude only**, or **Local only**.
  `registry.build_providers` is the single mode-aware source of providers; review and
  Ask both honor it, and Ask now works on a local-only setup.
- **Anthropic key verification + model picker** — Test calls `GET /v1/models` (free),
  proving the key and returning the models it can use; the model field becomes a
  dropdown of those ids. Rejected keys report "key rejected (401)".
- **Must-Have catalog** (Missing › Must-have picks): the engine studies a profile of
  the library and proposes canon feature films it's missing — acclaimed theatrical
  releases and Criterion-caliber world cinema. Proposals are hints only; nothing is
  stored unless TMDB data clears the anti-nonsense gates (resolves on TMDB / ≥200
  votes / ≥6.5 average / feature runtime / released / not adult / not owned / not
  dismissed). Dismissals are remembered; re-runs never duplicate (migration 0005).
  Without AI, the new Criterion + IMDb-top starter lists (pending human review) feed
  the same gates.
- **Scan flow**: phases reordered to Plex → Radarr → Tautulli → TMDB → finalize →
  score → **AI analysis** (auto advisory review; skips silently with no provider).
  `POST /api/scan` is idempotent (joins an in-flight run; retires stale RUNNING rows).
  The Setup Wizard silently starts the first scan the moment Plex + Radarr test green.
- **Login-first front door** — sign-in is the default screen; "New user? Set up Sift"
  shows only while no account exists.
- **Keep is permanent** — Junk's Keep persists as `movies.keep_override` (migration
  0006): protected titles never re-flag across rescans; drawer shows a Protected pill.

### Fixed
- **A–Z rail drifted off-screen on scroll** — the page container's transform
  animation demoted `position:fixed`; the rail is now portaled to `<body>`.
- Ollama connection hint now gives the one-line cloudflared tunnel command; Junk's
  dry-run note points at Settings › Autonomy instead of an env var.

### Fixed — audit of the new action/recommendation code
- **Dead-end drawer on Missing** — recommendation and curated-list posters opened the
  library drawer, but those titles aren't in the library, so it 404'd to "Not found."
  They now link out to the title's TMDB page (preview before adding), the affordance
  Radarr/Overseerr use for not-yet-owned titles.
- **Misleading recommendations note** — if every TMDB discovery call failed (bad key,
  outage), the user was told their library "already covers the graph well." The engine
  now tracks whether any anchor call reached TMDB and shows a "couldn't reach TMDB"
  note instead.
- **Live add no longer 500s on an unreachable Radarr** — resolving the root folder /
  quality profile is wrapped, returning the same graceful 400 as the empty-config case.
- **User monitor/unmonitor mislabeled as autonomous** — a manual toggle from the drawer
  now records `actor=user` instead of `auto` on the Activity trust surface.

### Added — taste recommendations + polish
- **Real "Recommended for you"** — the Missing screen's recommendations are no longer a
  stub. `analysis/recommend.py` seeds TMDB's discovery graph from your highest-rated
  owned titles (anchors), pulls `recommendations`/`similar` for each, aggregates and
  ranks candidates you don't own, and explains each ("Because you own X and Y").
  Deterministic — TMDB picks the candidates, Sift ranks and explains, never invents.
  `GET /api/missing/recommendations` degrades to a clear "connect TMDB" / "run a scan"
  note when it can't run.
- **Density toggle now does something** — the header's row-density button drove CSS
  variables nothing consumed. The library table now honours it (comfortable vs compact
  rows) and the tooltip says what it does.
- **Ask** — stale "add ANTHROPIC_API_KEY" hint replaced with a pointer to the in-app
  Settings › Connections (config moved into the UI).
- **Connections** — a live inline warning when a service URL points at
  ``localhost``/``127.0.0.1`` on a hosted instance (the #1 Ollama setup gotcha), shown
  before the Test round-trips and fails cryptically.
- **Activity** — added a "monitor" filter chip (monitor actions are common now that the
  drawer exposes them).

### Added — add/monitor/remove actions in the UI
- **Movie actions surfaced in the drawer** — Monitor/Unmonitor toggle + Remove
  (confirm-gated, dry-run aware) on any Radarr-managed title; a clear "not managed by
  Radarr" note otherwise. The **Missing** screen gains "+ Add" on collection gaps and
  starter-list titles. New `POST /api/actions/add` (autonomous, staged unless
  `SIFT_ACTIONS__DRY_RUN=false`) resolves the Radarr root folder + quality profile for
  live adds via `radarr_add`.
- **Fixed an id-conflation bug** — monitor/unmonitor/delete dispatch to Radarr
  endpoints keyed on Radarr's own movie id, not `tmdb_id`. The engine now resolves the
  stored `radarr_id` and refuses (clear error) any title Radarr doesn't manage; the
  golden delete-approval guard is unchanged. Safety tests seed `radarr_id` and assert
  live calls key on it.

### Added — smarter junk, curated lists, and AI review
- **Smarter junk classification** — a rule cascade over the rating score: adult →
  remove; cult classic → keep; US theatrical → keep; low + independent → remove;
  low + international (non-cult) → remove; else defer to the score. Facts come from
  TMDB enrichment (now run per scan, `enrich_limit`): `original_language`, `budget`,
  `is_adult`, `us_theatrical`, `is_independent` (migration 0003). Forced-removals are
  flagged even when well-rated; protected titles are kept even when low.
- **Curated lists** (migration 0004) — cult + IMDb-top starter lists (factual
  title+year, `review_status: pending`), resolved to TMDB ids via search during a
  scan (never hand-coded). Cult membership drives the "keep if cult" rule;
  `GET /api/missing/lists` surfaces list titles you don't own on the Missing screen.
- **AI review** — `OllamaProvider` + a route-by-task orchestration (local drafts →
  Anthropic refines; band-aware deterministic fallback). `POST /api/review/run`
  writes an **advisory** note on each junk candidate (never changes the deterministic
  verdict — §4/§7); the Junk screen gets a "Run AI review" button and shows the note.

### Added — Setup Wizard, login, in-app config, and reset
- **Username/password login** (single-user; stdlib PBKDF2 + stateless HMAC session
  tokens, no new deps). The API gate accepts a session token or the legacy static
  `SIFT_SERVER__API_TOKEN`, and stays open only until an account exists.
- **Setup Wizard** (first run): create the login → connect + **Test** each service →
  done. `AuthGate` now routes first-run → wizard, returning users → login,
  signed-in → app.
- **In-app connections** for Plex/Radarr/TMDB/Tautulli + **Ollama** URL/model and
  **Anthropic** key/model — stored on the server and overlaid on the env/toml base
  (no need to touch Render). `GET /api/config` masks secrets as `*_set` flags;
  `PUT` deep-merges and rebuilds the live services; `POST /api/config/test/{service}`
  probes unsaved values. A **Settings › Connections** editor and the wizard share one
  form (blank secret = keep the saved one).
- **Reset** (Settings › Account): factory-reset back to the wizard, with a
  **keep-thumbnails** variant that preserves the poster cache for fast re-scans.
- Verified end-to-end in a browser: wizard→dashboard, persistence across reload,
  login rejects bad passwords, reset returns to the wizard.

### Added — poster cache + Library A–Z jump
- **Thumbnails now load for every title.** New `GET /api/poster/{tmdb_id}` resolves a
  poster from the stored URL or by TMDB id, downloads it, and caches the bytes on
  disk keyed by id — fixing Plex-only titles (most of the library) that carry no
  Radarr artwork. The route accepts `?token=` so `<img>` tags authenticate; a shared
  `<Poster>` component falls back to the gradient placeholder on 404. Cache dir
  defaults beside the DB (`PostersConfig.cache_dir`) so a persistent disk covers it —
  this is the cache the upcoming "reset (keep thumbnails)" preserves.
- **Library A–Z rail:** when sorted by title, a letter rail jumps straight to titles
  starting with that letter via a new `starts_with` filter on `/api/movies`
  (`#` = digits/symbols). Verified in-browser: filter works, 0 broken images.

### Added — upgrade detector (cutoff-unmet)
- Deterministic **upgrade detector**: library titles whose current file is below
  Radarr's quality-profile cutoff. The verdict (`cutoff_unmet`) is read straight off
  the Radarr movie payload during ingestion — **no extra request** — and stored on
  the movie (migration `0002`, indexed). Kids items are included (an upgrade is never
  a removal, so there's no safety reason to guard them).
- `analysis/upgrades.py` (`candidates` ordered biggest-file-first, `count`), a new
  `GET /api/upgrades`, an `upgrades` figure on `/api/status` counts, and a
  `cutoff_unmet` filter on `/api/movies`.
- Frontend surfaces it in-design (no new screen): a **"Below cutoff"** quick filter
  on Library (deep-linkable via `?filter=upgrades`), an **"↑ upgrade"** badge in the
  table, and an actionable **"N titles below the quality cutoff"** callout on the
  Dashboard linking to the filtered library.
- Tests with negative controls: normalize extracts the flag (and ignores it when
  there's no file); the detector excludes meets-cutoff and non-Plex titles and orders
  by size; endpoint + status-count + Library-filter coverage.

### Added — live action execution (Phase 3)
- `POST /api/actions/{id}/execute` completes the action lifecycle over HTTP. The
  golden guard is preserved: an unapproved delete returns **403** and is never
  issued; already-executed/rejected actions return 409; unknown ids 404.
- `RadarrWriter` now builds a short-lived `RadarrClient` from `RadarrConfig` for
  each live write (add / monitor / unmonitor / delete), then closes it — nothing to
  dispose at shutdown. `ActionsConfig.dry_run` (env `SIFT_ACTIONS__DRY_RUN`,
  **default `true`**) is the master safety switch; the propose endpoint treats it as
  a floor, so a client can opt *into* staging but can never force a live write the
  operator hasn't enabled.
- `/api/settings` reports `actions_dry_run` so the UI can tell the truth. The **Junk**
  screen now runs propose → approve → **execute**, labels the result **"Removed"**
  (live) vs **"Removal staged"** (dry-run), and warns in the confirm dialog when a
  removal is real and irreversible.
- Tests: execute-endpoint approval guard + dry-run floor over HTTP; an end-to-end
  live-delete integration test proving an approved delete reaches Radarr
  (`DELETE /api/v3/movie/{id}?deleteFiles=true`) via a mock transport; and a
  negative control that a writer with no connection refuses (not silently no-ops) a
  live write.
- `docs/DEPLOY.md` documents the staged-vs-live switch.

## 2607.0.1 — Phase 0 foundations

Initial backend skeleton for the read-only ingestion MVP.

### Added
- Project scaffolding: `pyproject.toml` (hatchling, `sift` console script),
  `sift.toml.example`, `.env.example`, `.gitignore`, `README.md`, `CLAUDE.md`,
  and `docs/GAME_PLAN.md`.
- `config.py` — layered settings (env > `.env` > `sift.toml` > defaults) with
  `SecretStr` secrets for Plex/Radarr/Tautulli/TMDB and the server token.
- `db/models.py` — SQLAlchemy 2.x snapshot schema (movies, ratings,
  watch_history, collections, collection_members, people, movie_people, scores,
  profile, actions, scan_runs, settings) + `db/session.py` engine/session helpers
  (foreign-key + WAL pragmas).
- Alembic scaffolding (`alembic.ini`, `env.py`) with an initial migration.
- `clients/base.py` — async `httpx` base with retry/backoff-with-jitter, rate
  limiting, and secret redaction; `plex.py`, `radarr.py`, `tautulli.py`, `tmdb.py`
  clients each exposing a `health()` probe and the endpoints ingestion needs.
- `ingest/normalize.py` (canonical `tmdb_id` identity) and `ingest/pipeline.py`
  (resumable, per-phase-checkpointed scan emitting progress events).
- `actions/engine.py` + `actions/radarr_writes.py` — propose/approve/reject/execute
  with the **delete-requires-approval** invariant and dry-run payloads.
- `services/health.py`, `services/audit.py`.
- `api/` — `routes_health` (`/api/health`, `/api/status`), `routes_scan`
  (`/api/scan`, `/api/scan/{id}`), `routes_movies` (`/api/movies`,
  `/api/movies/{tmdb_id}`), and `ws.py` (`/ws/scan/{id}`); `main.py` app with
  optional static UI serving and API-token gating.
- `cli.py` — `sift serve|scan|init`.
- Test suite with mocked clients and negative controls, including the
  delete-safety invariant test.

### Added — frontend foundation
- React + Vite + TypeScript + Tailwind app in `frontend/`, built to static assets
  and served by FastAPI at `/` (with an SPA fallback so client routes deep-link).
- Design system from `docs/design/HANDOFF.md`: CSS-variable tokens for all three
  themes (Spatial Dark / Light / Neon), density + reduce-motion, the cyan→magenta
  identity, and Bricolage / Hanken / JetBrains Mono type.
- Global shell — floating frosted header (wordmark, `/`-focus global search,
  connection-health dots, density/theme toggles, scan pill, gradient Run-scan CTA),
  floating top-nav, drifting aurora backdrop, and a live scan panel over `/ws/scan`.
- Typed API client + hooks wired to the real backend; **Dashboard** (instrument
  cluster + health orb) and **Library** (grid/table, filters, pagination) read live
  data; **Activity** renders the audit feed; **Design System** is a live token sheet.
- Missing / Junk / Ask / Taste Profile / Settings ship as on-brand placeholders
  pending the Phase 1–2 analysis + AI backends.
- Verified end-to-end: `npm run build` clean, served by FastAPI, and rendered in a
  real browser across routes and themes. **Visual polish pending human sign-off.**
- CI gains a `frontend` job (npm ci + typecheck + build).
