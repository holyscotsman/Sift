# The recommendation list

**25,000 films worth owning.** This is the list Sift recommends from. It is
backend-only — nothing in the UI names it or says where a suggestion came from.

File: `backend/sift/data/canon_25k.json` (version `2026-08-20`)  
Rebuilt by: `python tools/canon/build_lists_from_imdb.py --basics … --ratings …`

## Where it comes from

Nothing here was chosen by hand or by a language model. Every entry traces to a
row in a public dataset or a published list:

| Pillar | Count | What it is |
|---|---|---|
| `imdb_wr` | 16,067 | Weighted-rating fill from IMDb's official datasets. This is the tranche that took the list from 10,000 to 25,000. |
| `popular` | 4,434 | Fame-ranked IMDb features — the films most people have actually seen. |
| `cult` | 2,769 | Wikipedia's list of cult films, full membership. |
| `criterion` | 1,683 | The Criterion Collection, full membership. |
| `oscar_winner` | 293 | Academy Award winners. |
| `film_registry` | 141 | US National Film Registry. |
| `festival_top_prize` | 99 | Palme d'Or, Golden Lion, Golden Bear. |
| `canon_patch` | 31 | Gap-fill from AFI, Sight & Sound, BFI 100 and box-office records. |
| `floor_override` | 31 | Canonical films below the rating floor, kept because an authoritative list names them. |
| `box_office` | 22 | Highest-grossing releases. |
| `bfi_100` | 14 | BFI Top 100. |
| `afi` | 1 | AFI 100 Years. |

## Metadata

Every entry carries what IMDb's datasets record about the film, so a
recommendation can be shown with context rather than as a bare title, and so
ranking has something to work with beyond a vote count.

| Field | Coverage | Source |
|---|---|---|
| `genres` | 24,580 (98%) | `title.basics` |
| `runtime` | 24,599 (98%) | `title.basics`, minutes |
| `directors` | 24,627 (99%) | `title.crew` → `name.basics`, up to 3 |

A field is **absent rather than null** when the source has nothing to say. An
entry with no `genres` means IMDb records none, not that the film has none — 360
of the 25,000 have no IMDb id at all (they arrived from Criterion or the cult list
by title), and 60 more are IMDb rows with the genre column genuinely empty,
mostly experimental cinema.

The filters that decide *membership* deliberately do not decide what is *known*.
An earlier pass built the fact table from the titles that survived the featurette
floor, which left 461 Criterion entries with no genres — *Sherlock Jr.*, *Simon of
the Desert*, *Zéro de conduite*: films that are in the canon on Criterion's word
and are also under an hour long. Facts are now collected before any filter runs.

Directors are capped at three. Anthology films — *Paris, je t'aime*, *New York
Stories* — list every segment's director, and past a handful the list stops being
an answer to "who made this".

## Tiers

Tier 1 is the strongest claim to canon, tier 4 the weakest. Tiers decide ranking,
and tiers 1–3 also protect a film you already own from the junk queue.

| Tier | Count |
|---|---|
| 1 | 4,433 |
| 2 | 5,883 |
| 3 | 6,500 |
| 4 | 8,184 |

## The rule that matters most

**A theatrical release is carried however badly it was received.** The vote floor
(1,000) is a floor on *reach* — did this film actually get in front of an
audience — and never on quality. A poorly rated theatrical film is in this list;
it simply ranks last. People watch bad films on purpose, and a recommender that
quietly deletes them is deciding something it was not asked to decide.

Two things are filtered out, and both are facts rather than opinions:

- **Under 60 minutes.** IMDb files hour-long documentaries and TV specials as
  `movie`. A featurette is not something you keep a copy of.
- **Adult titles.**

## A sample

The first twenty by rank. The full list is the JSON — 25,000 rows is not a
document, and pasting it here would only make it harder to search.

| Title | Year | Rating | Votes | Tier |
|---|---|---|---|---|
| The Shawshank Redemption | 1994 | 9.3 | 3,222,707 | tier 1 |
| The Godfather | 1972 | 9.2 | 2,246,384 | tier 1 |
| The Dark Knight | 2008 | 9.1 | 3,209,279 | tier 1 |
| The Lord of the Rings: The Return of the King | 2003 | 9.0 | 2,183,886 | tier 1 |
| Schindler's List | 1993 | 9.0 | 1,597,135 | tier 1 |
| The Godfather Part II | 1974 | 9.0 | 1,506,808 | tier 1 |
| 12 Angry Men | 1957 | 9.0 | 997,273 | tier 1 |
| The Lord of the Rings: The Fellowship of the Ring | 2001 | 8.9 | 2,227,094 | tier 1 |
| Inception | 2010 | 8.8 | 2,853,252 | tier 1 |
| Fight Club | 1999 | 8.8 | 2,645,897 | tier 1 |
| Forrest Gump | 1994 | 8.8 | 2,522,720 | tier 1 |
| Pulp Fiction | 1994 | 8.8 | 2,457,438 | tier 1 |
| The Lord of the Rings: The Two Towers | 2002 | 8.8 | 1,975,249 | tier 1 |
| The Good, the Bad and the Ugly | 1966 | 8.8 | 897,179 | tier 1 |
| Interstellar | 2014 | 8.7 | 2,585,671 | tier 1 |
| The Matrix | 1999 | 8.7 | 2,268,376 | tier 1 |
| Star Wars Episode V – The Empire Strikes Back | 1980 | 8.7 | 1,517,680 | tier 1 |
| Goodfellas | 1990 | 8.7 | 1,406,149 | tier 1 |
| Seven | 1995 | 8.6 | 2,047,443 | tier 1 |
| The Silence of the Lambs | 1991 | 8.6 | 1,740,679 | tier 1 |

## Changing it

Do not edit `canon_25k.json`; the next rebuild overwrites it. Put corrections in
`backend/sift/data/list_overrides.json`, which the generator never touches.

```json
{
  "always_recommend": { "titles": [ { "imdb_id": "tt0111161" } ] },
  "never_recommend": { "titles": [ { "title": "Some Film", "year": 2004 } ] }
}
```

**It takes effect on the next scan, on titles already stored as well as new
ones.** `always_recommend` seeds the title into the canon at tier 1 — the reason
to write it here is that the generated list got it wrong, so the generated list
does not outrank it. `never_recommend` keeps the title from being seeded *and*
deletes the row if one is already there; without that second half a correction
would be silently inert against everything that shipped, which is nearly the
whole list.

Give an `imdb_id` where you have one. A `title` + `year` pair also works and
matches whether or not the stored row carries an id — deliberately the opposite
of how `exclude_list.json` behaves, because that list is generated and id-keyed
while this one is a person writing down a decision with whatever they had to
hand. A film named in both sections stays out: only one of the two readings can
lose a film for ever.

## Source

IMDb Datasets — <https://datasets.imdbws.com/> (`title.basics`, `title.ratings`).
Free for personal and non-commercial use. Not affiliated with IMDb. Criterion and
cult membership from Wikipedia (CC BY-SA).
