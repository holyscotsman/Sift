# The exclusion list

**23,937 films Sift will never recommend.** Direct-to-video and
made-for-TV releases — the B-picture and C-picture end of the catalogue.

File: `backend/sift/data/exclude_list.json` (version `2026-08-20`)  
Rebuilt by: `python tools/canon/build_lists_from_imdb.py --basics … --ratings …`

## The rule

> IMDb classifies the title as `video` (direct-to-video) or `tvMovie`.

That is a fact about **how the film was released**, recorded at publication. It is
not a judgement about whether the film is any good, and that distinction is the
whole design. Nobody sat down and decided these films were bad — including me,
which is exactly why this list can be trusted and a hand-written one could not.

| Release type | Count |
|---|---|
| `tvMovie` | 16,128 |
| `video` | 7,809 |

## What is *not* the rule

**A low rating never excludes anything.** A theatrical release stays recommendable
however badly it was received. Quality is expressed by ranking, never by removal.

## The escape hatch

A direct-to-video or TV title rated **7.0 or better with 25,000+ votes** is kept
out of this list. A large audience rating something highly is evidence it is not
schlock, whatever channel it came out on.

Without this the rule deleted 52 films people genuinely want, including Spielberg's
*Duel*, *The Animatrix*, the DC animated features and the 1966 *Grinch*. That was
found by looking at what the first version of this list actually caught, not by
guessing — and it is the reason the escape hatch exists at all.

## A sample

The twenty most-watched entries. These are the ones most likely to come up, and
they read as a fair description of what the list is for.

| Title | Year | Type | Rating | Votes |
|---|---|---|---|---|
| High School Musical | 2006 | tvMovie | 5.7 | 106,581 |
| The Lion King II: Simba's Pride | 1998 | video | 6.4 | 83,872 |
| American Pie Presents: Band Camp | 2005 | video | 5.0 | 80,240 |
| American Pie Presents: The Naked Mile | 2006 | video | 5.1 | 78,441 |
| High School Musical 2 | 2007 | tvMovie | 5.3 | 72,874 |
| American Pie Presents: Beta House | 2007 | video | 5.3 | 71,391 |
| Sharknado | 2013 | tvMovie | 3.3 | 57,121 |
| Gia | 1998 | tvMovie | 6.9 | 55,315 |
| American Pie Presents: The Book of Love | 2009 | video | 4.7 | 52,451 |
| The Lion King 1½ | 2004 | video | 6.5 | 51,540 |
| Wrong Turn 2: Dead End | 2007 | video | 5.5 | 50,789 |
| Home Alone 4: Taking Back the House | 2002 | tvMovie | 2.6 | 44,443 |
| Camp Rock | 2008 | tvMovie | 5.3 | 41,975 |
| Aladdin and the King of Thieves | 1996 | video | 6.3 | 41,026 |
| Hostel: Part III | 2011 | video | 4.6 | 39,752 |
| Death Race 2 | 2010 | video | 5.6 | 36,453 |
| Undisputed 4: Boyka | 2016 | video | 6.9 | 35,098 |
| The Return of Jafar | 1994 | video | 5.8 | 34,639 |
| Son of Batman | 2014 | video | 6.7 | 34,585 |
| Tremors II: Aftershocks | 1996 | video | 6.0 | 34,113 |

## Changing it

Do not edit `exclude_list.json`; the next rebuild overwrites it. Corrections go in
`backend/sift/data/list_overrides.json`, which the generator never touches — and
`never_recommend` there is the one place a judgement call belongs, because it is
yours rather than a dataset's.

## Source

IMDb Datasets — <https://datasets.imdbws.com/> (`title.basics`, `title.ratings`).
Free for personal and non-commercial use. Not affiliated with IMDb.
