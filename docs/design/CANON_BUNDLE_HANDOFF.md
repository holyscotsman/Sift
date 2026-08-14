# Sift canon + algorithms — drop-in bundle

One artifact, everything from the design sessions. Unzip at the **repo root**
(the folder containing `backend/` and `docs/`); paths land where they belong.

## Install — three commands

```bash
cd /path/to/Sift
unzip -o sift-canon-bundle.zip
git checkout -b canon-integration && git add -A && git commit -m "canon + algorithm bundle (design docs, data, tooling)"
```

## Then start Claude Code and paste

```
/goal implement docs/design/INTEGRATION.md steps 1-6 in order, honoring the
phase checks in docs/design/JUNK_ALGORITHM_V2.md and
docs/design/ACQUISITION_ALGORITHM.md and the owner decisions in
INTEGRATION.md section 4b. One coherent change per turn. Not met until:
CanonEntry is populated and resolving within budget, the Canon tab and
coverage figure are live, scores_v2 computes in shadow with the tier 1-3
shield (NULL-safe, with a negative control), the similarity table drives the
affinity term with TMDB fallback, tier-1 batch request exists behind confirm
and the dry-run floor, and every new guard has a red-verified negative
control. Step 7 (cutover) is excluded: it requires owner review. Stop after
250 turns regardless.
```

Run it in tmux with the machine kept awake (`caffeinate -is` on macOS), with
auto mode on — a goal does not change permissions by itself.

## What's in the box

| Path | What |
|---|---|
| `backend/sift/data/canon_10k.json` | 10,000 validated must-have titles (v2026-08-14.6, all tiered) |
| `backend/sift/data/canon_starter.json` | 549 hand-curated, categorized overlay |
| `backend/sift/data/similarity_ml25m.json` | CF similarity: top-25 neighbors for 4,781 titles from 25M ratings |
| `docs/design/INTEGRATION.md` | THE ENTRY POINT — sequencing, schema, owner decisions §4b |
| `docs/design/JUNK_ALGORITHM_V2.md` | Junk scoring v2 (Appendix A verified against the code) |
| `docs/design/ACQUISITION_ALGORITHM.md` | Must-watch discovery incl. §2.2b similarity layer |
| `docs/design/VALIDATION.md` | Canon coverage vs 10 authoritative lists |
| `docs/design/AUDIT.md` | Audit findings incl. the NULL-tier shield fix |
| `tools/canon/*.py` | Regeneration scripts (canon build, sweep, similarity) — rerun quarterly against fresh IMDb/Wikipedia/MovieLens snapshots |

## Decisions already made (do not re-ask)

Owner-locked in INTEGRATION.md §4b: floor overrides included (31 films),
conservative thresholds (junk 70 / borderline 50), Tautulli engagement at full
weight, Missing ranked tier → taste-affinity → fame. Canon shield: tiers 1–3
hard-protect owned titles, tier 4 advisory.

## What the app looks like when it's done

Missing gains a Canon tab ("2,340 of 10,000 owned") ranked by tier then your
taste; one confirm-gated "Request tier 1" batch; the Junk queue shrinks to
high-confidence candidates that nothing canonical, curated, or watched can
enter; and every verdict still shows its arithmetic in the drawer.
