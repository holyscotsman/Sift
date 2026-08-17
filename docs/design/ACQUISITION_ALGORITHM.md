# Acquisition — how Sift knows what should be on the server but isn't

Companion to `docs/design/JUNK_ALGORITHM_V2.md`. Junk answers "should this stay";
this answers "what belongs here that I don't have". The two are mirrors and share
machinery — one recognition engine, one calibration mechanism, one eval
discipline — so read the junk spec first; its §3 constraints apply here verbatim
and are not repeated.

Suggested location: `docs/design/ACQUISITION_ALGORITHM.md`. The starter canon
data file ships alongside as `data/canon_starter.json`.

---

## 0. What already exists — build on it, replace nothing

Sift already has most of the plumbing, built across 2607.9.0–2607.12.0 and the
unreleased must-have work. The implementer maps this first, the same way Junk v2
Task 0.1 maps scoring:

- **A private canon** of theatrical-scale films worth owning: TMDB's top-rated
  chart, a revenue-sorted blockbuster sweep, curated lists (cult / IMDb-top /
  Criterion), gated curator picks. Backend-only; Missing shows the diff.
- **The diff is against Plex membership only**, deliberately ignoring Radarr
  wanted-lists (2607.9.0). Preserve this: "Radarr knows about it" is not
  "I have it".
- **Requested titles leave Missing** with a visible count, and a staged (dry-run)
  add correctly stays listed because it reached nothing (2607.12.0).
- **Taste recommendations** (`analysis/recommend.py`): anchors from
  highest-rated owned titles seed TMDB's `recommendations`/`similar` graph;
  candidates aggregate, rank, and carry "Because you own X and Y" explanations.
- **The must-have engine** proposes canon gaps, with the anti-nonsense gates:
  resolves on TMDB / ≥200 votes / ≥6.5 average / feature runtime / released /
  not adult / not owned / not dismissed. Dismissals are remembered (migration
  0005); re-runs never duplicate.
- **Curated lists are stored as factual title+year**, resolved to TMDB ids by
  search during a scan, **never hand-coded** (2607.9.0). The canon file below
  follows this convention exactly.
- **Collections** has a gap view with one-click fill.

What's missing is unification: four sources with four ad-hoc rankings and no
shared score, no structural completion beyond collections, no freshness
mechanism, and no learning from which suggestions the owner actually acts on.

---

## 1. The asymmetry, inverted

Junk v2's governing rule is that removal needs overwhelming evidence because a
false removal is catastrophic. Acquisition inverts cleanly:

- **Suggesting is nearly free.** A wrong suggestion costs screen space and a
  dismissal click. The bar for *appearing in the list* is therefore modest —
  one good reason suffices, exactly as one good signal keeps a film off the
  junk list.
- **Requesting is an action.** It consumes disk, bandwidth, and an Overseerr
  approval. Auto-requesting is where the high bar lives: Sift never requests
  without an explicit owner act (the existing per-item and Request-all flows,
  both confirm-gated, both subject to the server dry-run floor).

So the design freedom is in ranking, not gating: show generously, order
ruthlessly, act only on instruction.

---

## 2. How Sift can know — the four sources of evidence

No single source can answer "what belongs on this server". The list is a
triangulation, and each source covers a failure mode of the others.

### 2.1 External consensus — what the world agrees is worth owning

The canon. Two halves with different jobs:

- **The static starter canon** (`data/canon_starter.json`, shipped with this
  spec): ~300 time-tested titles across consensus masterworks, world cinema,
  cult, genre pillars, animation, documentaries. Hand-curated, stable,
  deliberately conservative about the most recent ~18 months — a hand list of
  "recent essentials" goes stale the month it's written.
- **The dynamic sweeps** (exist today): TMDB top-rated chart and
  revenue-sorted discovery, refreshed per scan, bounded pages. **Recency is
  their job.** A 2026 release earns canon membership through the chart sweep,
  not through anyone editing a file.

Consensus covers the failure mode of taste-only systems: a library built purely
from "more like what you have" never discovers anything orthogonal.

### 2.2 The household's demonstrated taste — what *this* server is for

The taste graph, with one correction imported from the TV recommendations
design. 2607.20.0 established for shows that **finishing is the signal that
survives** — ratings seed toward acclaim, behavior seeds toward truth. Apply the
same lesson to films:

- **Anchors v2** = films the household watched to high completion (and anything
  `keep_override`-protected — an explicit Keep is a taste statement), weighted
  by recency of watch. Fall back to the current highest-rated-owned anchors only
  when watch history is thin (evidence weight again).
- Each anchor pulls TMDB `recommendations` + `similar` (two bounded calls, the
  existing pattern). Candidates rank by **agreement, not acclaim**: three
  anchors pointing at one title outranks one anchor pointing at something
  better-reviewed — the 2607.20.0 rule, applied to films.
- Every candidate keeps its provenance for the UI: "Because you watched X and Y".

### 2.2b Collaborative-filtering similarity (`data/similarity_ml25m.json`)

The advanced layer under the taste graph: **item–item adjusted-cosine
similarity precomputed from the MovieLens 25M rating matrix** (25M ratings,
162k users; per-user mean-centered so generous and harsh raters compare
fairly). 4,781 canon titles carry top-25 canon-member neighbors each —
"households that loved X also loved Y" as measured arithmetic, not metadata
adjacency. Spot-validated: Godfather→Godfather II (0.665), Spirited Away→the
Ghibli cluster, Alien→Aliens/Blade Runner.

Runtime use is pure lookup — deterministic, offline, zero API calls:

```
affinity(candidate) = Σ over anchors a of sim(a, candidate)
```

summed over the household's completion-based anchors (§2.2), then blended into
the §3 score as the `affinity` term. TMDB's graph remains the fallback for the
~half of canon (mostly post-2019 and deep obscurities) outside ml-25m's
coverage — the two compose, they don't compete. The table is a versioned data
file regenerated by `tools/canon/build_similarity.py` against future MovieLens
snapshots; it never changes at runtime, so the determinism constitution holds.

Taste covers the failure mode of consensus: the canon doesn't know this
household watches everything Michael Mann ever shot.

### 2.3 Structural completion — gaps the data can prove

Deterministic set arithmetic, no judgment involved. Highest-precision source in
the system:

- **Collection gaps** (exists): own two of a trilogy → the third. Extend
  ranking: completion fraction matters — owning 5 of 6 outranks owning 2 of 6.
- **Filmography gaps** (new): for directors where the household owns ≥ N
  (start 3) films *with demonstrated engagement on at least one*, surface the
  missing films that pass the gates, ranked by recognition. The engagement
  clause is the negative control built in: owning three bulk-imported Uwe Boll
  films must not trigger a completionist sweep of the rest.
- **Franchise gaps**, gated exactly as recognition's franchise fame is gated
  (theatrical release) so direct-to-video sequels don't ride in.

TMDB cost: collection membership is already enriched; director filmographies
are one `person/{id}/movie_credits` call per qualifying director, bounded by a
per-scan cap and cached in a table — Constraint 4 discipline (preload, set math
in memory, bulk write; the Missing diff itself stays zero-per-title-queries).

### 2.4 The owner's own record — ground truth for calibration

Every Overseerr request, every add with `actor=user`, every must-have dismissal
is a label: *this household, shown this title, said yes / said no*. Exactly the
Junk v2 §6 mechanism, pointed the other way — used offline to fit the ranking
weights, proposed as a config diff, applied through Settings as an audited
action. Never online, never AI.

---

## 3. One score for all sources

Today each source ranks its own list. v2 normalizes every candidate — canon
gap, taste hit, structural gap, must-have proposal — into one **acquisition
score** so the Missing page can show one honestly-ordered queue (with the
existing tabs preserved as filters over it):

```
affinity   = agreement-weighted taste-graph strength (0 when no anchor points here)
consensus  = recognition score, reused verbatim from recognition.py
structure  = completion bonus: collection/filmography fraction owned, engagement-gated
freshness  = decay on suggestions repeatedly shown and never acted on

score = w_a·affinity + w_c·consensus + w_s·structure − w_f·staleness
```

- **`recognition.py` is shared with Junk v2 deliberately.** The same per-decade
  percentile that protects an owned obscurity from removal ranks an unowned
  classic for acquisition. One engine, two directions; a bug fixed once fixes
  both.
- **Confidence and abstention apply** (Junk v2 §5.2): a candidate with thin
  TMDB data doesn't get a confident mid-rank — it abstains out of the list.
  The existing hard gates (≥200 votes etc.) already enforce most of this;
  abstention formalizes the remainder.
- **Freshness** (new table: `suggestion_history` — Constraint 3): a candidate
  shown for K consecutive scans with no request and no dismissal decays
  deterministically (`staleness = min(1, scans_shown / 12)`), so the list
  breathes instead of fossilizing. A dismissal remains permanent suppression
  (existing behavior). Decay never removes a structural gap — an incomplete
  trilogy stays visible because it stays true.
- **Ordering is total**: `(−score, −vote_count, tmdb_id)`. Determinism rules
  from Junk v2 §3 apply — same fixture, same output, any hash seed.

Gates stay hard preconditions ahead of scoring, with one deliberate carve-out:
**entries flagged criterion, cult, or any authoritative-canon source
(oscar_winner / festival_top_prize / film_registry / afi / bfi_100 /
floor_override) are exempt from the ≥200-votes and rating gates** — membership
is their credential. This mirrors 2607.13.0's curated-list floor, and per the
owner's 2026-08-14 decision it extends to canonical films below 6.0
(Cavalcade, Cimarron, Emilia Pérez et al.). Without the carve-out those gates
would strip exactly the so-bad-it's-good cult canon (Manos at 1.7,
Battlefield Earth at 2.5) and the award-record films the sweep restored. All
other gates apply to every entry without exception: resolves on TMDB, feature
runtime, released, not adult, **not owned (Plex), not already requested, not
dismissed**. Pin both directions with tests: a sub-6.5 cult-flagged title
survives ingest; a sub-6.5 unflagged title does not.

---

## 4. Evaluation — built first, same discipline as Junk v2 §7

`bench/acquisition_golden.py` extends the seeded fixture with planted
households. Golden cases, each with a paired negative control:

| Setup | Expected |
|---|---|
| Owns Fellowship + Two Towers, both watched | Return of the King near the top (structure) |
| Owns 5 Nolan films, 3 watched to completion | missing Nolan films surface (filmography) |
| Owns 3 films by one director, none ever played | **no** filmography sweep (engagement gate) |
| 3 anchors' graphs all point at one title | it outranks a better-rated single-anchor title (agreement > acclaim) |
| Canon title, 40 TMDB votes | never appears (vote gate) |
| Canon title, announced/unreleased | never appears (released gate) |
| Title dismissed last month | never reappears (permanent suppression) |
| Title requested and live-added | gone from Missing, counted (2607.12.0) |
| Title requested via **staged** add | still listed (2607.12.0 — it reached nothing) |
| Owned title in the canon | never suggested (the diff itself) |
| Same fixture, different hash seed | identical list, identical order |

Metrics to `docs/optimization/metrics.jsonl`, report-only in `verify.sh`:
`gate_precision` (nothing gated slips through — target 1.0),
`structural_recall` (planted completions found — target 1.0),
`order_stability` (target 1.0), `canon_coverage` (% of canon owned — a
descriptive number the dashboard can show, not a target), and once live,
`request_rate` / `dismissal_rate` per source — the honest measure of whether
the ranking matches the household, and the input to §2.4 calibration.

Baseline the current Missing/recommendations output before changing anything.

---

## 5. The starter canon file

`data/canon_starter.json`, shipped with this spec. Format follows the repo's
curated-list convention (2607.9.0):

- **Factual title + year only.** TMDB ids are resolved by search at scan time,
  never hand-coded. A title that fails to resolve is skipped and logged, not
  stored.
- Every entry enters with `review_status: pending` and must clear the
  anti-nonsense gates before storage — the file is input to the gates, not a
  bypass of them.
- Categories are organizational metadata for the UI ("From the canon: world
  cinema"), not scoring inputs; membership in *any* canon category feeds the
  same consensus term.
- The file is versioned and additive. Removing a title from a future version
  does not un-suggest it retroactively; dismissal is the owner's mechanism.
- One deliberate bias, stated so it can be argued with: the list stays
  conservative on the most recent 18 months (a handful of already-consensus
  titles only), because recency belongs to the dynamic chart sweep, which
  refreshes itself.

### 5.1 The expanded canon (`data/canon_expanded.json`)

A second, data-generated file gives the canon depth: 10,000 films
(`data/canon_10k.json`) composed of four pillars. The first three define
canon-worthiness; the fourth targets the owner's actual stated pain — "the
movie I want tonight is never on my server" — which is a fame-coverage
problem, not a quality problem:

1. **Criterion Collection membership** — the full film list (Wikipedia,
   CC BY-SA), 1,683 titles, spine numbers preserved where parsed.
2. **Cult classics** — the complete Wikipedia cult-films list (A–Z, built from
   academic cult-cinema references), 2,769 titles. 519 titles sit on both
   lists.
3. **Theatrical consensus fill** — ~1,100 slots from the official IMDb
   datasets: feature films ≥5,000 votes ranked by Bayesian weighted rating
   (`WR = v/(v+m)·R + m/(v+m)·C`, m=25000), tiered by rank.
4. **Popular favorites** — 5,000 titles ranked by raw fame (vote volume), the
   watch-desire pillar. Floors, per owner instruction: rating ≥ 6.0 (no bad
   movies), and non-English-original titles additionally require rating ≥ 7.0
   and ≥ 25k votes (no low-rated international padding). Fame ordering is
   deliberate: for "will someone reach for this on a random night," a 6.9-rated
   film with 900k votes beats a 7.8 with 15k.

Composition, matching, and ordering are deterministic; the method is recorded
in the file header so the file can be regenerated from fresh snapshots.

Load-bearing details:

- **Membership weighting.** Criterion or cult membership is a curated floor —
  tier-1 equivalent, per 2607.13.0: these are exactly the titles vote counts
  cannot defend. `imdb_wr` fill entries weight by tier
  (1.0 / 0.75 / 0.5 / 0.3). Starter-file titles floor at tier-1 regardless.
- **Resolution.** 93% of entries carry an IMDb tconst — source data, not a
  hand-coded TMDB id — resolved exactly via TMDB `/find/{imdb_id}`. The
  remainder (mostly Criterion shorts, TV-adjacent releases, and alternate
  foreign titles) resolve by title+year search, the repo convention.
  Resolution MUST be budgeted per scan like `tmdb_enrich_limit`; 5,000 lookups
  never run in one scan. Unresolved entries aren't in the canon yet — the diff
  degrades gracefully.
- **The gates still apply.** The file is candidacy, not verdict: adult,
  runtime, released, owned, dismissed filtering happens at ingest exactly as
  for every other source — this is also what drops the handful of
  non-features that ride in on the Criterion list. The tier weight, the
  gates, and the owner's dismissals — not hand-editing the file — keep the
  queue sane.

---

## 6. Phases

Ordered, gated on checks, no timelines. One loop iteration per coherent change.

- **Phase 0 — Map and measure.** Document the existing canon build,
  recommendation ranking, and must-have gates from the code (Appendix A here,
  like Junk v2's). Build the golden fixture and baseline the current output.
  *Check: baseline metrics line exists; goldens discriminate.*
- **Phase 1 — Canon ingest.** Ship `data/canon_starter.json` through the
  existing curated-list resolution path; dashboard `canon_coverage` figure.
  *Check: resolution logs show skip-not-store on failures; coverage number
  matches a hand count on the fixture.*
- **Phase 2 — Unified score.** Normalize existing sources into the §3 score
  behind the existing UI (tabs become filters over one queue). Shadow-diff the
  ordering change like Junk v2 §8.1.
  *Check: gate_precision 1.0, order_stability 1.0, statement pin holds.*
- **Phase 3 — Anchors v2.** Completion-based anchors with rating fallback.
  *Check: agreement-beats-acclaim golden passes; thin-history fixture falls
  back.*
- **Phase 4 — Structural completion.** Filmography + franchise gaps with the
  engagement gate and TMDB call caps.
  *Check: Uwe Boll control holds; per-scan TMDB budget respected.*
- **Phase 5 — Freshness + calibration.** `suggestion_history` decay; §2.4
  offline fit producing proposed weight diffs.
  *Check: decay never hides a structural gap; runtime unchanged until a diff
  is applied.*

---

## 7. Non-goals

- **No auto-requesting.** Sift proposes; the owner disposes. The dry-run floor
  and per-item approval remain untouched.
- **No availability/streaming-service awareness** — no new paid APIs, no new
  infrastructure.
- **No TV acquisition changes** — TV suggestions keep their own deliberate
  design (eight, finished-show-seeded); this spec is films.
- **No AI-decided membership.** The must-have engine's proposals remain
  advisory and gate-checked; the gates and the score are the deciders.
- **No scraping.** TMDB is the only external source, within existing bounds.

## Appendix A — current acquisition pipeline, verified against the code (2026-08-14)

Phase 0's map is DONE — read from the repo at commit 4933902.

- **Curated seed**: `backend/sift/data/curated_seed.py` — `CURATED_SEED` dict of
  `(title, year)` tuples keyed by list name (cult / imdb_top / criterion),
  seeded into `CuratedListEntry` by `services/curated_lists.py:34`. The
  docstring explicitly invites "importing a fuller list" — the canon files are
  that fuller list.
- **`CuratedListEntry`** (`db/models.py:309-322`): list_name(32) / title /
  year / nullable tmdb_id / review_status default "pending"; unique on
  (list_name, title, year); resolved by TMDB search during scans. **No imdb_id
  column** — and columns cannot be added (`create_all`), which is why the 10k
  import needs its own table (integration doc §2).
- **`CanonMovie`** (`db/models.py:346+`): PK tmdb_id; built deterministically in
  `services/canon.py:169` from TMDB top-rated + revenue discovery + curated
  lists + gated must-haves; Missing = canon minus Plex.
- **TMDB client** (`clients/tmdb.py`): has `search_movie(title, year)`,
  `top_rated`, `discover`, `get_recommendations`, `get_similar` — **no
  `/find/{imdb_id}` endpoint yet**. Add `find_by_imdb()` for exact resolution
  of the 10k's ids (96.4% coverage); it is one small method on the existing
  base client.
- **Anchors are rating-based today**: `analysis/recommend.py:4` — "highest
  external rating, tie-broken by vote count". §2.2's completion-based anchors
  v2 is a genuine change, and mirrors the shipped TV lesson (2607.20.0,
  `tv_recommend`).
- **Junk floor consumes the same tables**: `junk.py:_canon_ids()` unions
  CanonMovie + resolved CuratedListEntry into `recognition`'s 0.75 floor — the
  two-way canon (§0 of the integration doc) is already how the code is shaped.
