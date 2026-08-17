# Audit report — canon + algorithm bundle, 2026-08-14

Requested by the owner ("run a complete audit and double check it — I feel
like it's not advanced enough"). Two halves: defects found, and an honest
assessment of the "advanced enough" question.

## Defects found and fixed

**1. NULL-tier shield bypass (severity: high, would have shipped broken).**
3,933 criterion/cult entries carried `tier: null`, and the integration's
shield predicate is `CanonEntry.tier <= 3` — NULL fails every SQL comparison,
so the *most curated* class would have been silently excluded from junk
protection while looking protected on paper. Fixed in canon 2026-08-14.6:
curated membership is now explicit tier 1; every entry carries an integer
tier (1: 4,433 / 2: 2,133 / 3: 2,000 / 4: 1,434). The lesson matches the
repo's own conventions: the shield test must include a negative control with
a NULL-adjacent case.

**2. Three resolver mismatches posing as canonical films (caught earlier,
recorded here).** "Crossfire (2023)", "Fists of Bruce Lee (1978)", "Wings
Over Everest (2019)" reached the floor-override candidate list through
title-collision resolution. Excluded from the override; the rating floor
catching them first is defense in depth, not luck to rely on — the loop
should add a resolution-sanity test (source-list year within ±3 of resolved
year).

## Verified clean

- 10,000 entries exactly; zero duplicate IMDb ids; zero duplicate title+year;
  every entry has sources and an integer year; 9,640 exact IMDb ids (96.4%).
- 31 floor overrides present, tier 2, dual-tagged `canon_patch` +
  `floor_override`.
- External coverage (VALIDATION.md): AFI 100%, Sight & Sound 100%,
  Oscars/Registry/festivals/BFI 95–98% with residuals itemized as
  shorts/docs/deliberate exclusions.
- Similarity table: 4,781 titles, top-25 canon neighbors, adjusted cosine,
  spot checks pass (Godfather→Godfather II 0.665, Ghibli clusters, Tarantino
  clusters). Deterministic ordering with movieId tiebreak.

## Design notes surfaced by the audit (accepted, documented)

- In the v2 score sketch, the quality-deficit term is not damped by
  protection; with the `w_q ≤ w_rec/3` cap its maximum contribution is below
  any band boundary, so a fully protected film cannot cross into junk on
  quality alone. Intentional; pin with a test.
- Popular-pillar tiers 2–3 fall inside the shield. Redundant rather than
  wrong: their recognition contribution is ≈0 anyway (famous by construction).
- The similarity table covers ~half the canon (ml-25m ends ~2019 and needs
  ≥300 ratings). TMDB-graph fallback covers the rest; coverage will be
  reported per-candidate in the UI provenance so thin evidence is visible.

## Is it advanced enough? An honest answer

What "advanced" cannot mean here: the repo's constitution (docs/ENGINEERING.md §4,
ARCHITECTURE §2) forbids AI-decided verdicts, and every ranking must be
deterministic and explainable. A neural scorer deciding deletions is off the
table *by design*, and that design is correct for an app that proposes
irreversible actions.

What advanced legitimately means, and where the bundle now stands:

1. **Collaborative filtering — ADDED.** The taste layer is no longer
   metadata adjacency: it is item–item similarity over 25M real ratings
   (§2.2b), precomputed to a data file, deterministic at runtime. This is the
   same mathematical family Netflix-era recommenders are built on, expressed
   in a form the constitution permits.
2. **Learning from the owner — SPECIFIED.** Offline logistic fit over
   keep/remove/request/dismiss labels producing proposed weight diffs through
   the audited propose→approve path (junk spec §6). Deliberately not online
   learning.
3. **Calibrated abstention, hysteresis, decay — SPECIFIED.** Evidence-mass
   abstention, band stickiness, exponential recency decay replacing cliffs:
   these are the unglamorous pieces that make a scorer trustworthy, and they
   are where the v1 code is weakest (the cliff at `scoring.py:98` is live
   today).
4. **What is deliberately absent**: embeddings-based content similarity
   (poster/plot vectors), LLM taste inference, online bandits. Each either
   violates determinism, adds paid infrastructure, or optimizes a metric this
   app cannot measure. If a future owner decision relaxes the constitution,
   the eval harness built in Phase 0 is what would keep such additions honest.

The gap between this bundle and "a hand-tuned heuristic" is now: an external
validation suite, a collaborative-filtering layer, an owner-calibration loop,
and an eval harness that every future change must beat. That is what advanced
looks like under a determinism constraint.
