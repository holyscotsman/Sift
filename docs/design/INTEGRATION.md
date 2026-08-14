# Integration — wiring the canon and both algorithms into Sift

The capstone document. Three artifacts exist; this specifies how they become
app behavior. Read alongside `docs/design/JUNK_ALGORITHM_V2.md` (owned films:
keep or cut) and `docs/design/ACQUISITION_ALGORITHM.md` (missing films: what
to get). This document does not repeat their contents; it sequences them and
specifies the connective tissue.

## 0. The two-question model — the frame everything hangs on

| | Question | About | Data spine |
|---|---|---|---|
| Acquisition | "Is this a good movie I'm missing?" | The world's films | `data/canon_10k.json` + taste graph |
| Junk | "Does this file deserve its disk here?" | Owned files | recognition + engagement + protections |

They are not one axis. A bad movie can be a keep (Battlefield Earth: cult).
A fine movie can be junk (competent, anonymous, unwatched). "Good" is a fact
about the world; "junk" is a fact about this household. 2607.13.0 is the
in-repo proof of what happens when the two are conflated.

**The canon is the shared spine, used in both directions:**
- On the canon + not owned → acquisition candidate (ranked by tier + fame).
- On the canon + owned → junk protection (see §3).

## 1. Files into the repo (paths grounded in the clone, commit 4933902)

```
backend/sift/data/canon_10k.json         # 10,000 validated (beside curated_seed.py,
backend/sift/data/canon_starter.json     #   whose docstring invites this import)
backend/sift/data/similarity_ml25m.json  # CF similarity table (acquisition §2.2b);
                                         #   loaded once at startup, pure lookups,
                                         #   no DB table needed
docs/design/JUNK_ALGORITHM_V2.md
docs/design/ACQUISITION_ALGORITHM.md
docs/design/INTEGRATION.md               # this file
docs/design/VALIDATION.md                # canon provenance + coverage evidence
docs/design/AUDIT.md                     # audit findings incl. the NULL-tier fix
tools/canon/*.py                         # regeneration scripts (canon, sweep, similarity)
```

## 2. Canon ingest — one new table, two small touchpoints

Grounded against the real schema. `CuratedListEntry` cannot hold the import
(no `imdb_id` column, and `create_all` never adds columns), so:

- **`CanonEntry`** (new table, deploys free): `id` PK, `imdb_id?` (indexed),
  `title`, `year`, `tier` (1–4), `sources` JSON, `spine?`, `tmdb_id?` nullable
  indexed, `resolve_attempts`, `review_status` default "pending", `file_version`.
  Loaded from `canon_10k.json` at scan start when `file_version` is new —
  same seeding pattern as `services/curated_lists.py:34`.
- **`clients/tmdb.py` gains `find_by_imdb(imdb_id)`** (`GET /find/{id}?`
  `external_source=imdb_id`) — exact resolution for the 96.4% of entries
  carrying ids; `search_movie(title, year)` (exists, `tmdb.py:75`) for the
  rest. **Budgeted per scan** like `tmdb_enrich_limit` (~400/scan → resolved
  in ~25 scans; the UI says the queue is still filling). Three failures →
  `review_status: unresolvable`.
- **Membership stays set math**: canon tmdb_ids preloaded in one statement,
  diffed in memory — the `_CHUNK`/preload discipline already used by
  `junk.py:_iter_scores`. Pin with the statement-count test pattern.

## 3. Canon → junk: the shield (owner decision, 2026-08-14)

The mechanism ALREADY EXISTS: `junk.py:_canon_ids()` (64–74) unions
`CanonMovie` + resolved `CuratedListEntry` ids, and `recognition.py:144-150`
floors recognition at `_CANON_FLOOR = 0.75` for that set. The shield is one
touchpoint:

```python
# junk.py:_canon_ids — add:
ids.update(session.scalars(
    select(CanonEntry.tmdb_id).where(
        CanonEntry.tmdb_id.is_not(None), CanonEntry.tier <= 3)))
```

Tier 4 stays OUT of the floor set and instead contributes a small advisory
protection term in scores_v2 (JUNK_ALGORITHM_V2.md §4.5 P2.5):

```
P2.5  canon tier 1-3 (owned)  → recognition floored at 0.75 (existing mechanism)
      canon tier 4 (owned)    → advisory bonus only; can still flag
```

Rationale: tiers 1–3 are curated/award/consensus canon — definitionally
should-haves, so proposing their deletion contradicts the acquisition side of
the same app. Tier 4 is fame-fill; famous-but-unwatched mediocrity is
precisely what the junk queue exists to surface. Negative control pair: an
owned tier-2 title with zero plays never enters the junk queue; an owned
tier-4 title with zero plays and low engagement still can.

Absence from the canon is **not** evidence of junk (10,000 ≠ all good films —
the asymmetry rule from both specs applies).

## 4. Canon → acquisition: ranked queue + tier-1 batch (owner decision)

- Missing page gains a **Canon tab**: unowned canon titles ranked by
  `(tier, -votes, tmdb_id)`, with pillar badges (Criterion spine, cult, award,
  festival) and the existing per-title Request button.
- **One batch action: "Request tier 1"** — the few-hundred best unowned canon
  titles, routed through Overseerr, arm-on-first-click + confirm like every
  existing batch action, server dry-run floor applies. No other tier gets a
  batch button. No auto-requesting: storage math (10k ≈ 50–80 TB) makes
  unbounded acquisition a disk incident, and the reclaim ledger's planner is
  the tool for deciding what space exists to spend.
- Dashboard gains a **canon coverage figure** ("You have 2,340 of 10,000") —
  descriptive, not a target; it is the honest measure of the original
  complaint ("the movie I want is never on my server") shrinking over time.

## 4b. Owner decisions — locked 2026-08-14, encode as config defaults

1. **Floor overrides included**: 31 canonical-but-below-6.0 films are in the
   canon (`sources: ["canon_patch","floor_override"]`), including Best Picture
   winners Cavalcade, Cimarron, The Broadway Melody, and Emilia Pérez. Three
   resolver mismatches stay out.
2. **Junk thresholds: conservative.** Ship `JunkThresholds` defaults as
   `junk_cutoff: 70.0`, `borderline_cutoff: 50.0` (config.py:161-163 currently
   60/40). The Settings live preview (`junk.preview`) already lets the owner
   tune from there.
3. **Tautulli has years of history**: engagement runs at full evidence weight;
   completion-based anchors v2 (acquisition §2.2) is viable from day one — no
   thin-history fallback needed at launch.
4. **Missing ranking: blend** — `(tier ASC, taste_affinity DESC, votes DESC,
   tmdb_id)` — canon tier leads, the taste graph breaks ties within a tier,
   fame last. Total order, deterministic.

## 5. Sequencing — one loop, phases interleaved

Run inside the existing autoloop/goal discipline; each item is one-to-a-few
iterations, gated by its spec's checks:

1. **Junk spec Phase 0** — reconcile docs vs code (Task 0.1: the true current
   composition; ARCHITECTURE.md §5 and CHANGELOG 2607.13.0 disagree), build
   the junk eval harness, record v1 baseline.
2. **Canon ingest** (§2 above) + coverage figure. Independent of scoring;
   ships value immediately.
3. **Acquisition spec Phase 0–1** — map existing canon/recommend/must-have
   code; goldens; wire `canon_titles` into the Missing diff (Canon tab).
4. **Junk spec Phase 1** — `scores_v2` shadow mode, including the P2.5 shield.
   Shadow-diff shows every title whose band the shield changes.
5. **Tier-1 batch request** endpoint + UI (§4), behind the existing action
   gates.
6. **Junk spec Phases 2–4** and **Acquisition Phases 2–5** as specced,
   eval-gated, one measured change per iteration.
7. **Cutover** per junk spec §8.2 — owner reviews the shadow diff; not
   unattended.

## 6. The goal command

```
/goal implement docs/design/INTEGRATION.md steps 1-6 in order, honoring the
phase checks in JUNK_ALGORITHM_V2.md and ACQUISITION_ALGORITHM.md. One
coherent change per turn. Not met until: canon_titles is populated and
resolving within budget, the Canon tab and coverage figure are live, scores_v2
computes in shadow with the P2.5 shield and the shadow-diff endpoint works,
tier-1 batch request exists behind confirm + dry-run floor, and every new
guard has a red-verified negative control. Step 7 (cutover) is excluded: it
requires owner review. Stop after 250 turns regardless.
```

## 7. Open items

- **Repo URL still needed** for grounding this document in real file paths and
  the true scoring composition; until then the loop's reconciliation step
  (junk spec Task 0.1) carries that burden.
- The 38 canonical-but-below-6.0 exclusions (VALIDATION.md) await an owner
  call; default is excluded.
- The Sonarr re-grab guard (ARCHITECTURE.md §6) remains a blocker for applied
  TV downgrades — unrelated to this work, listed so it isn't forgotten.
