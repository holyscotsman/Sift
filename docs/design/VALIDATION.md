# Canon validation report — 10,000-title must-have list

Version validated: `canon_10k.json` 2026-08-14.4. Every number below is
reproducible from the build scripts and cached source snapshots.

## Method

The list was compared against every major published film canon with a
parseable public list — none of which were inputs to the original build except
where noted. Each source entry was resolved to an IMDb id (collapsing title
variants like "Star Wars" vs "Star Wars: Episode IV – A New Hope"), classified
as covered / genuine gap / non-feature / below the owner's quality floor /
unresolvable noise, and genuine gaps were added to the list under a
canon-source exemption. The list stays exactly 10,000: 535 gap additions
displaced the 535 lowest-fame entries of the popularity fill.

## Final coverage (feature films, after patch)

| Source | Coverage |
|---|---|
| AFI 100 Years...100 Movies (1998) | 121/121 — 100% |
| AFI 100 Years...100 Movies (2007) | 124/124 — 100% |
| Sight & Sound Greatest Films 2022 | 15/15 parseable — 100% |
| Academy Award–winning films (all categories, ~1,400) | 96.2% |
| National Film Registry | 96.9% |
| Palme d'Or winners | 97.0% |
| Golden Lion winners | 97.0% |
| Golden Bear winners | 97.3% |
| BFI Top 100 British films | 98.0% |
| All-time highest-grossing charts | 95.3% |

The residual percentage in every row is dominated by the same two categories,
both deliberate: films below the owner's ≥6.0 rating floor (listed below), and
award winners that are shorts or documentaries outside the feature-film gates.

## What the sweep added (535 titles)

Predominantly: Oscar winners below the fame threshold (Kolya, Divorce Italian
Style, Moscow Does Not Believe in Tears, A Letter to Three Wives), festival
top-prize winners (The Son's Room, Eternity and a Day, The Wedding Banquet),
National Film Registry features (House of Usher, All That Heaven Allows), and
BFI-listed British classics (The Dam Busters, Room at the Top, Gregory's
Girl). These are exactly the titles a fame-ranked list structurally misses:
canonical, well-rated, modestly voted.

## Canonical below-floor films — overridden by owner decision (2026-08-14)

31 films on authoritative lists but below the 6.0 rating floor are now
INCLUDED, flagged `floor_override` (canon version 2026-08-14.5): the Best
Picture winners Cavalcade, Cimarron, The Broadway Melody; Emilia Pérez;
Suicide Squad; Transformers: Age of Extinction; the rest per
`validation_data.json → excluded_below_floor`. Three entries from that list
remain excluded because they were resolver mismatches, not canonical films:
"Crossfire (2023)", "Fists of Bruce Lee (1978)", "Wings Over Everest (2019)"
— the floor catching those is the guard working in depth. With the overrides
included, residual non-coverage on the award/registry/festival sources is now
almost purely shorts and documentaries outside the feature gates.

## Known limits — stated, not hidden

- **Sources skew English-language and Western.** The festival and Criterion
  pillars partially correct this; a Bollywood/Nollywood/East-Asian popular
  canon would need dedicated sources.
- **Wikipedia's Sight & Sound page yields only the top entries in parseable
  form**; the poll's deeper 250 was not swept.
- **Letterboxd-era popularity** (streaming-native favorites with low IMDb
  engagement) has no fetchable list here.
- **"Complete" means converged**: the last sources swept (festivals, BFI,
  registry) contributed overlapping candidates, and the final additions are
  sub-300-vote obscurities — the marginal authoritative source now adds
  approximately nothing above the floors. Completeness against unpublished
  taste is not a claim this or any list can make; that is what Sift's
  taste-graph and the owner's own request/dismissal history are for.

## Provenance

- IMDb official datasets (datasets.imdbws.com), snapshot 2026-08-14: ids,
  ratings, votes, runtimes, types.
- Wikipedia (CC BY-SA), snapshots cached 2026-08-14: Criterion Collection film
  list, cult films A–Z, AFI both editions, Sight & Sound 2022, Academy
  Award–winning films, National Film Registry, Palme d'Or, Golden Lion, Golden
  Bear, BFI Top 100, highest-grossing films.
- Composition, matching, and ordering: deterministic scripts
  (`build_canon_v2.py`, `build_canon_10k.py`, `patch_canon.py`), rerunnable
  against fresh snapshots.

## Integrity

10,000 entries; 9,640 carry exact IMDb ids (96.4%); zero duplicate ids; zero
duplicate title+year pairs; every addition ≥6.0 rating and ≥200 votes and
feature runtime; popularity floors unchanged (≥6.0, international ≥7.0/25k).
