# Junk v2 — what deserves to be on the server, and how Sift should decide

A design spec for the next generation of the keep/junk decision. Written against
`ARCHITECTURE.md` at 2607.24.0 and the full `CHANGELOG.md`. Intended to be handed
to the improvement loop and implemented phase by
phase, each phase verified before the next begins.

Suggested location in the repo: `docs/design/JUNK_ALGORITHM_V2.md`.

---

## 0. Before writing any code: reconcile the docs with the code

The two documents this spec is built from disagree on the current composition,
and the implementer must resolve that against the code first.

- `ARCHITECTURE.md` §5 says `scoring.py` composes **rating (weight 0.6)** and
  **engagement (weight 0.4)**, bands `junk ≥ 60`, `borderline ≥ 40`.
- `CHANGELOG.md` 2607.13.0 says rating was **demoted to a tiebreaker
  (1.0 → 0.2)** and recognition became the primary driver, with curated-list
  floors and franchise gating.

Both cannot be the whole story. Likely the recognition-primary composition lives
in `classify.py`/`recognition.py` as an overlay while `scoring.py` kept its old
weights, or `ARCHITECTURE.md` §5 is stale. **Task 0.1: read `scoring.py`,
`classify.py`, `recognition.py`, and write the true current composition — every
signal, weight, floor, and override, in order of application — into this
document's Appendix A.** Everything below assumes that map exists.

Also verify before starting (each is a documented behavior that v2 must not
regress):

1. Never-played does not condemn (2607.13.0). Confirm the engagement signal
   contributes protection when plays exist and approximately nothing when they
   don't — not a penalty.
2. Watch history reaches films through *all* Plex copies (2607.14.0 fixed plays
   being dropped for non-surviving rating keys). Confirm the join path.
3. Titles not yet TMDB-enriched fall back rather than scoring as unrecognised
   (2607.13.0). Confirm the fallback path and what triggers it.
4. Kids-section items score but never auto-flag. Find the guard and its test.
5. `keep_override` is permanent and survives rescans (migration 0006).
6. Home Videos are excluded upstream by metadata agent, so they never pollute
   scoring inputs (2607.18.0).

---

## 1. What "junk" means

**A film is junk when its continued presence has neither demonstrated value nor
plausible option value to this household.** Operationally, all three must hold:

1. **No public footprint** — the world at large does not know or care about this
   title, judged against its own era's peers, not against modern vote volumes.
2. **No household engagement** — nobody here has watched it, started it, or
   deliberately protected it.
3. **No protection fact** — it is not on a curated list, not a theatrical or
   studio-scale release, not kids content, not explicitly kept, and not
   something the owner asked for.

Junk is a statement about *belonging*, not about disk. Size never makes a film
junk — a 40 GB remux of a beloved film is a reclaim-ledger finding
(re-encode), not a junk finding. The two systems stay separate, as they are
today. Junk is also **films only, permanently** — the TV exclusion in
`ARCHITECTURE.md` §7 stands.

### The asymmetry that governs everything

A false positive (flagging a film the owner wanted) costs a re-download at best
and an unnoticed loss at worst. A false negative (missing some junk) costs a few
gigabytes of disk that the reclaim ledger will partially recover anyway. So the
bar mirrors the downgrade bar in `suitability.py`: **removal requires multiple
independent lines of evidence; keeping requires only one.** One genuine signal
of value — a real watch, a curated-list membership, a theatrical run, an
explicit request — outvotes any amount of obscurity.

This is the same shape as the existing design ("an upgrade needs one signal, a
downgrade needs all of them") and v2 keeps it as the organizing principle rather
than an exception list.

---

## 2. What exists today, and the defects v2 addresses

Current pipeline (verify in Task 0.1): `scoring.py` produces a 0–100 composite
with per-signal contributions in a `signals` JSON blob; `classify.py` overlays a
rule-cascade verdict (adult → remove; cult → keep; US theatrical → keep;
low + independent → remove; low + international non-cult → remove; else defer);
`recognition.py` scores public footprint with per-decade vote normalization,
curated-list floors, and theatrical-gated franchise fame.

This is already a sound two-layer architecture — a continuous score plus a
categorical verdict overlay — and v2 **refines both layers rather than replacing
the shape**. The known defects, from the changelog's own record:

- **Hard time cutoffs.** `unwatched_years` is a cliff: a film watched 2.9 years
  ago and one watched 3.1 years ago should not sit in different worlds.
- **Engagement is coarse.** "Plays" conflates finished-and-loved with
  abandoned-at-ten-minutes. Mean completion exists but its interaction with
  recency and play count isn't principled.
- **No abstention.** `suitability.py` returns "insufficient evidence — no
  verdict" as a first-class outcome; the junk score always produces a number,
  even when almost nothing is known about a title. Partial evidence should
  produce an explicit abstain, not a confident-looking mid-range score.
- **No stability guarantee.** Nothing prevents a title flapping between
  borderline and junk across consecutive scans as signals wobble. Band changes
  should be sticky.
- **Intent is invisible.** A film the owner requested through Overseerr last
  month and a film that arrived in a bulk import ten years ago carry identical
  weight. The request *is* evidence of wantedness and it's already in the
  database (`actions` audit trail, Radarr add records).
- **The owner's own verdicts are unused.** Every Keep press
  (`keep_override`), every approved removal, every dismissal is a labeled
  example of this household's taste, sitting in the database, currently
  informing nothing.

---

## 3. Hard constraints — inherited, non-negotiable

These come from `ARCHITECTURE.md` §2/§5/§9 and govern every phase below.

1. **Determinism.** No verdict may depend on hash seed, iteration order, wall
   clock, or an AI call. Ties break with `tv_size.dominant()` semantics — toward
   the outcome that makes a destructive suggestion look *smaller*. Every ranking
   sort key must be total.
2. **AI never decides correctness.** AI review stays advisory: it may annotate a
   junk candidate, never move a score, band, or verdict. `analysis/` keeps zero
   model calls.
3. **`create_all` adds tables, never columns.** All new persistent state goes in
   **new tables**. No new columns on `movies`, `scores`, or any deployed table.
4. **Round trips dominate in production, and tests can't see them.** The scoring
   pass is pinned by *statement count* (`test_scoring_cost.py` pattern —
   0.009 statements per film at 2607.24.0). v2 must extend that pin, not break
   it: preload in chunked `IN` batches, compute in memory, write in bulk.
5. **Negative controls and mutation verification.** Every new guard ships with a
   paired test proving it isn't over-broad, and controls are verified by
   breaking the implementation and watching the test go red.
6. **`main` auto-deploys to Render** (`render.yaml`, `autoDeploy: true`).
   Algorithm work happens on a branch, and lands on `main` only in shadow mode
   (Phase 1) until cutover criteria are met (Phase 5).
7. **Kids guard and `keep_override` survive.** Both are absolute vetoes on
   auto-flagging, before any score is consulted.

---

## 4. Signal architecture

Five signal groups. Each produces a value in [0, 1], a **evidence weight**
(how much data actually backed it), and a human-readable detail string for the
`signals` blob — the drawer must be able to say *why* in plain language.

### 4.1 Recognition — does the world know this film?

Keep the 2607.13.0 design: per-decade vote-volume percentile (a 1954 film is
judged against 1954 peers), theatrical run, studio-scale budget (≥ $20M),
franchise fame gated on theatrical release, cast footprint. Rating is not an
input. Curated-list membership floors the result.

v2 refinements, each measured before keeping (Phase 3):

- **Percentile, not thresholds.** Where the current code uses stepped tiers,
  compute the title's vote-count percentile within its decade cohort directly.
  Store cohort medians in a new `recognition_cohorts` table refreshed per scan
  so scoring stays zero-round-trip.
- **Library-relative floor.** A library that is 40% Criterion titles is telling
  you obscurity is the *point* of this collection. If the owner's keep-rate for
  low-footprint titles is high (from Phase 4 labels), the recognition weight
  self-attenuates. This is a config value produced by calibration, not a
  runtime lookup.

### 4.2 Engagement — has this household demonstrated value?

Replace cliffs with decay, and make the signal strictly protective (its floor is
"contributes nothing", never "condemns"):

```
recency  = exp(−ln 2 · years_since_last_play / half_life)      # half_life ≈ 2.5y, calibrated in Phase 4
depth    = plays_weighted · completion_quality
protect  = 1 − (1 − recency·w_r) · (1 − depth·w_d)             # noisy-OR: either alone protects
```

- `completion_quality` distinguishes finished (≥ `low_completion_pct`… verify
  the existing constant) from sampled-and-abandoned. A film watched to 95% twice
  is strong protection. A film abandoned at 8% once is *weak* protection — but
  still ≥ 0, never negative. Abandonment is not evidence of junk; it is absence
  of evidence of value. (This is the never-played-cannot-condemn rule, extended
  to barely-played.)
- Plays must aggregate across **all** `PlexCopy` rows for the film — the
  2607.14.0 lesson, now load-bearing.
- Evidence weight: 1.0 when Tautulli was reachable for the scans covering the
  ownership period; reduced when history is short or Tautulli was skipped in
  preflight (that fact is in `scan_runs.checkpoints`). A film owned for three
  weeks with no plays has *thin* absence-of-engagement, not damning
  absence-of-engagement.

### 4.3 Quality consensus — the tiebreaker

Bayesian-shrunk rating exactly as today (prior 6.0, low vote counts pulled to
prior), demoted per 2607.13.0: it may separate two equally unrecognised,
equally unwatched titles, and may never outvote recognition or engagement.
Cap its weight so that `w_quality < min(w_recognition, w_engagement) / 3` holds
structurally, and pin that with a test — this ratio is the 2607.13.0 fix
("3,200 people agreeing a film is bad pushed it further toward deletion")
expressed as an invariant instead of a memory.

### 4.4 Intent and provenance — did someone here ask for this?

New signal group; the data already exists.

- **Explicit request** — an Overseerr/Radarr add recorded in the `actions`
  audit trail with `actor=user`, or a Radarr `added` date with a manual add
  method. Strong protection with slow decay (half-life ~4y): a film you asked
  for four years ago and never watched is drifting toward ordinary unwatched.
- **Monitored in Radarr** — mild protection; monitored means Radarr is actively
  maintaining it, which someone chose at some point.
- **Bulk provenance** — arrived in a mass import with thousands of siblings on
  the same date. Not a junk signal by itself (the asymmetry rule), but it sets
  the evidence weight of *absent* intent to full: for a bulk-imported title, "no
  one asked for this" is actually known, rather than merely unrecorded.

### 4.5 Protection facts — the cascade, formalized

The `classify.py` cascade survives as ordered, named rules. v2 states each rule
as `(name, precondition-facts, verdict, precedence)` in one table in the code,
so the drawer can show which rule fired and tests can enumerate them:

```
P0  keep_override            → KEEP   (absolute, owner said so)
P1  kids_section             → NEVER-AUTO-FLAG (score still computed and shown)
P2  curated_list (cult/criterion/imdb-top) → KEEP floor
P3  us_theatrical | studio_scale_budget | major_studio_streaming → KEEP
P4  adult                    → REMOVE (existing forced-removal rule)
P5  low_score + independent + non_cult        → REMOVE candidate
P6  low_score + international + non_cult      → REMOVE candidate
P7  otherwise                → defer to score band
```

Every P-rule gets a negative-control test (P3's control: a direct-to-video
franchise spin-off with a famous name is **not** protected — the gate already
exists, keep it pinned).

---

## 5. Composition, confidence, and bands

### 5.1 The score

Keep the additive 0–100 composite with per-signal contributions (the `signals`
blob format is good and the UI depends on it). The junk-pointing direction is
computed as *removal pressure minus protection*:

```
pressure   = w_rec · (1 − recognition)                 # obscurity presses toward junk
protection = noisy_or(engagement.protect, intent.protect)
score      = 100 · clamp(pressure · (1 − protection) + w_q · quality_deficit, 0, 1)
```

The multiplicative `(1 − protection)` form is the asymmetry made arithmetic: full
protection zeroes any amount of obscurity pressure, while zero protection leaves
pressure untouched. Exact weights are Phase 4's calibration output; ship Phase 1
with weights matched to reproduce the current score's rank order (see 8.1).

### 5.2 Confidence and abstention

```
evidence_mass = Σ (evidence_weight_i · w_i) / Σ w_i
```

Below `MIN_EVIDENCE` (start at 0.5, calibrate), the title's band is
**`insufficient`** — a first-class outcome rendered as "not enough to say", as
`suitability.py` already does. An un-enriched title, a film owned for a week, a
scan where Tautulli was down — all abstain rather than guess. Abstained titles
never enter the junk queue.

### 5.3 Bands, with hysteresis

Bands stay `junk / borderline / keep` (plus `insufficient`). To stop flapping:
a title changes band only when the new score clears the boundary by ≥ 3 points,
or when a P-rule's facts changed. The previous band lives in the v2 score table
(new table — Constraint 3). Pin with a test: a title at 59.0 that rescores 60.5
stays `borderline`; at 63.1 it moves.

### 5.4 Ordering

The junk queue sorts by `(band, −score, −bytes_on_disk, tmdb_id)` — total,
deterministic, size as tiebreaker only. Bytes come from `MediaFile` sums already
computed for the ledger; do not add per-title queries (Constraint 4).

---

## 6. Learning from the owner without breaking determinism

The database already contains labels: every `keep_override`, every approved and
executed removal, every dismissed must-have. v2 uses them **offline only**:

1. `tools/calibrate_junk.py` (new, stdlib + stdlib-adjacent only) reads all
   labeled titles, extracts their v2 signal vectors, and fits weights — plain
   logistic regression, fixed seed, deterministic output. If the label count is
   under ~30, it says so and refuses: fitting five parameters to nine keeps is
   how you memorize noise and call it taste. With few labels, ship the
   hand-set weights from 8.1 — they are the fallback, not a lesser mode.
2. Its output is a **proposed config diff** — before/after weights, and the
   eval-set delta (Phase 0 metrics) that change would produce — written to a
   report file. Nothing changes at runtime.
3. The owner applies the new weights through Settings (stored in the `settings`
   table like any config). The apply is an audited `Action`.

This is propose → approve → execute, applied to the algorithm itself. Runtime
scoring stays deterministic arithmetic over stored facts; the *weights* evolve
only through the same gate every other mutation passes. No online learning, no
AI in the loop, and a weight change is one audited row you can point at when
the queue looks different this week.

---

## 7. The evaluation harness — built first, before any signal changes

Nothing in sections 4–6 gets implemented before this exists. An algorithm change
without an eval set is a guess with confidence; the changelog's own history
(2607.13.0's Animal Farm / Battlefield Earth test) shows the project already
knows this.

### 7.1 The golden set

A committed fixture, `bench/junk_golden.py`, of synthetic titles with known
correct answers, built from the changelog's own canonical cases:

| Profile | Expected |
|---|---|
| Famously bad, theatrical, studio-scale ("Battlefield Earth") | keep (P3) |
| 1954 classic, modest modern votes ("Animal Farm") | keep (per-decade recognition) |
| Acclaimed, heavily voted, never played ("unwatched Schindler's List") | keep (recognition alone suffices) |
| Obscure 1976 indie, no list, no votes, never played, bulk-imported | junk |
| Criterion-listed obscure art film, never played | keep (P2 floor) |
| Direct-to-video spin-off of a famous franchise, no theatrical run | not protected by P3; judged on its own signals |
| Kids-section title, any signals | never auto-flagged (P1) |
| Un-enriched title (no TMDB data) | insufficient — abstain |
| Watched-to-completion last month, zero votes | keep (engagement alone suffices) |
| Abandoned at 8% once, obscure, bulk import | junk (weak protection loses to full-evidence obscurity) |
| Owner-requested via Overseerr 3 months ago, unwatched | keep (intent) |
| Same, 6 years ago, still unwatched | borderline (intent decayed) |

Plus planted junk and protected titles in the existing seeded bench fixture
(`bench/fixture.py`), which is already shaped like a real library — long
unwatched tail, outliers. Note the fixture-invalidates-baselines caveat from
`ARCHITECTURE.md` §9 applies: adding golden titles changes cohort medians, so
regenerate baseline numbers when the fixture changes.

### 7.2 Metrics — one JSON line each, appended to `docs/optimization/metrics.jsonl`

- **`removal_precision`** — of titles banded `junk`, the fraction whose golden
  label is junk. **Target: 1.0.** This is the headline. A miss here is the
  catastrophic direction.
- **`junk_recall`** — of golden junk, the fraction banded `junk`. Maximize
  subject to precision staying at 1.0.
- **`abstention_correctness`** — insufficient-evidence titles that were
  genuinely thin, vs abstentions on titles with plenty of data (lazy abstention
  is how recall quietly dies).
- **`band_stability`** — fraction of titles keeping their band across two scans
  of identical underlying data with different hash seeds and row orders
  (`PYTHONHASHSEED` varied — the 2607.24.0 determinism lesson as a metric).
  Target: 1.0.
- **`owner_agreement`** (once Phase 4 labels exist) — leave-one-out: fraction of
  the owner's historical decisions the current weights reproduce.
- **`statements_per_film`** — the existing cost pin, extended to cover v2.
  Must not regress from 0.009.

`bench/bench_junk_eval.py` runs all of it on the fixtures and prints the line.
Wire into `verify.sh` / the loop as report-only, per the existing convention.

### 7.3 Baseline

Run the harness against the **current** algorithm before changing anything and
record the numbers (`"iter": 0, "item": "junk-v1-baseline"`). Every subsequent
claim of improvement is a diff against this line. If the current algorithm
already scores 1.0 precision and high recall on the golden set, the golden set
is too easy — extend it until it discriminates.

---

## 8. Storage and rollout

### 8.1 Shadow mode

New table `scores_v2` (Constraint 3 — a new table deploys free): `tmdb_id`,
`score`, `band`, `previous_band`, `confidence`, `signals` JSON, `computed_at`.
The scan's score phase computes **both** v1 and v2 every run. The UI keeps
showing v1. Initial v2 weights are tuned (by hand, on the eval harness) to
reproduce v1's rank order on the fixture within tolerance — proving the plumbing
before changing the answers.

A new report — `GET /api/junk/shadow-diff`, surfaced on the Storage or Junk
screen behind a small link — lists every title where v1 and v2 disagree on
band, with both signal breakdowns side by side. The owner reads real
disagreements on their real library. This is the only honest eval that exists
for taste: golden sets check the rules; the shadow diff checks the *judgment*.

### 8.2 Cutover criteria

v2 replaces v1 in the UI only when all of:

1. `removal_precision = 1.0` and `junk_recall ≥ v1` on the golden set.
2. `band_stability = 1.0` across hash-seed-varied runs.
3. `statements_per_film` within pin.
4. The owner has reviewed the shadow diff on their live library and not vetoed
   outstanding disagreements.
5. Two consecutive scans in shadow with no v2 crash and no abstention rate
   above 20% (abstaining on a fifth of a mature library means evidence weights
   are mis-calibrated, not that the library is mysterious).

After cutover, v1 keeps computing for two more releases (cheap — same preloaded
data), then is removed. `scores` stays for history; nothing rewrites it
(the 2607.24.0 convention: history is not rewritten).

---

## 9. Implementation phases

Ordered; each ends with its verification. No phase starts until the previous
one's checks pass. No timeline attached — the gate is the checks.

- **Phase 0 — Reconcile and measure.** Task 0.1 (Appendix A written from the
  code). Build `bench/junk_golden.py`, `bench/bench_junk_eval.py`, record the
  v1 baseline. *Check: baseline metrics line exists; golden set discriminates
  (v1 fails at least one case — if it fails none, extend the set).*
- **Phase 1 — Shadow plumbing.** `scores_v2` table, dual computation in the
  score phase, weights tuned to mimic v1, shadow-diff endpoint. *Check:
  rank-order agreement with v1 ≥ 95% on fixture; statement pin holds; UI
  unchanged.*
- **Phase 2 — Signal upgrades, one at a time, each measured.** Order: decay
  replaces cliffs (4.2) → abstention (5.2) → hysteresis (5.3) → intent (4.4) →
  recognition percentiles (4.1). One signal per iteration of the loop; after
  each, run the harness and keep or revert on the numbers. *Check per signal:
  golden metrics moved in the right direction or the change is reverted and the
  negative result logged.*
- **Phase 3 — Cascade formalization.** P-rule table with per-rule tests and
  negative controls, drawer shows the fired rule. *Check: every P-rule has a
  red-verified control.*
- **Phase 4 — Calibration.** `tools/calibrate_junk.py`, label extraction,
  proposed-diff report, Settings apply path as an audited action.
  *Check: leave-one-out `owner_agreement` reported; runtime provably unchanged
  until a diff is applied.*
- **Phase 5 — Cutover** per 8.2, then v1 removal two releases later.

Each phase is one-to-a-few loop iterations. The loop's existing rules apply:
one coherent change per iteration, measure before keeping, log negative
results in `docs/optimization/LOOP_LOG.md`.

---

## 10. Non-goals — pinned, so they stay non-goals

- **No TV junk scoring.** The §7 exclusion is a product decision, not a gap.
  The existing no-verdict-in-payload test stays.
- **No size-based junk.** Disk cost lives in the reclaim ledger. A junk finding
  never cites bytes as a reason (bytes may order the queue, never justify a
  flag).
- **No AI in any verdict path** — including the calibration fit, which is
  classical statistics with a fixed seed, not a model call.
- **No online learning.** Weights change only through the audited apply path.
- **No multi-user modeling.** One household, one taste profile.
- **No new paid infrastructure.**

---

## Appendix A — current composition, verified against the code (2026-08-14)

Task 0.1 is DONE — read from the repo at commit 4933902. The docs contradiction
is resolved: both described real paths.

**Main path** (TMDB enrichment has reached the title —
`analysis/scoring.py:186-190`):

| Signal | Weight | Effective share | Source |
|---|---|---|---|
| recognition (obscurity) | 1.0 | 62.5% | `scoring.py:151-165` |
| engagement | 0.4 | 25% | `scoring.py:71-110` |
| rating (Bayesian) | 0.2 (demoted via `replace()`) | 12.5% | `scoring.py:189` |

**Fallback path** (no enrichment yet — `scoring.py:191-194`): rating 0.6 +
engagement 0.4 — this is what ARCHITECTURE.md §5 was describing.
`compose()` normalizes over available signals only (`scoring.py:121-127`).

**Thresholds** (`config.py:152-163`): min_votes 50, rating_floor 5.0,
prior 6.0, unwatched_years 3, low_completion 0.25, junk ≥60, borderline ≥40.

**Verified behaviors** (§0 checklist): never-played contributes 0.0 with the
Schindler's List comment in place (`scoring.py:81-88`) ✓; enrichment-absent
titles fall back rather than scoring unrecognised (`junk.py:128-141`) ✓; kids
guard excluded from candidates (`junk.py:228-236`) ✓; `keep_override` filtered
in the candidates query (`junk.py:234`) ✓; classification overlay
protect/remove/neutral applied in `junk.py:_is_candidate` (207-219) ✓.

**Canon floor already exists**: `recognition.py:144-150` floors recognition at
`_CANON_FLOOR = 0.75` for titles in `junk.py:_canon_ids()` (64-74) =
`CanonMovie` ∪ resolved `CuratedListEntry`. The v2 shield (§ integration doc)
extends this set, it does not invent the mechanism.

**Findings the phases should exploit:**

1. `recognise()` accepts `in_franchise` and `cast_fame` (`recognition.py:113-114`)
   but `junk.py:131-138` never passes them — dead parameters. Radarr collection
   membership is already ingested; wiring `in_franchise` is nearly free.
2. The engagement cliff is real: `scoring.py:98-100` hard-thresholds on
   `unwatched_years` — the §4.2 decay replaces exactly this.
3. Ties inside `_best_ratings` are already order-pinned (`junk.py:38-49`) —
   the determinism conventions are live; extend, don't re-fight.

## Appendix B — formulas

```
bayesian_rating   r̂ = (v·r + m·p) / (v + m)          p = 6.0 prior, m = existing vote pivot (read from code)
recency_decay     e = exp(−ln2 · Δt_years / H)        H = half-life, per-signal (engagement 2.5y, intent 4y, calibrate)
noisy_or          P(a, b) = 1 − (1−a)(1−b)            protection composition: either alone suffices
evidence_mass     M = Σ(eᵢ·wᵢ) / Σwᵢ                  eᵢ ∈ [0,1] data-backedness of signal i
score             s = 100 · clamp(w_rec·(1−R) · (1−P) + w_q·Q_deficit, 0, 1)
hysteresis        band changes iff |s − boundary| ≥ 3 or P-rule facts changed
tie order         (band, −score, −bytes, tmdb_id)     total; dominant() semantics for any modal value
```
