# Optimization Cycle 09 — plan

Target version: **2607.16.0**. Safety rails unchanged (deletes approval-gated,
dry-run default, AI advisory-only) and extended: a transcode is treated as
irreversible and gated identically.

## The question this cycle answers

Sift could say whether a film deserved to be on the server. It could not say
where the disk was going, and for TV it could say nothing at all — all sixteen
tables were keyed on `Movie.tmdb_id`, and `pipeline.py` skipped any Plex section
that was not a movie section.

Five things were asked for: duplicate episodes ranked by the space they would
return; shows using more than their share, normalised for episode count; HD/SD
recommendations including seasons that disagree with themselves; a plan for
driving Handbrake later; and film files that are too large or suspiciously small.
The stated goal was one dependable procedure rather than five reports.

## 1. Measure before judging

**Problem.** `Movie.file_size` is a bare byte count and `Movie.quality` is
Radarr's free-text profile name, so nothing downstream could tell a three-hour 4K
remux from a bloated ninety-minute 1080p.

**Change.** A `media_files` table holding size, duration, resolution and codec —
one row per file, for movies and episodes alike, so every later query works on one
shape. The data was already arriving: `normalize_radarr_movie` opened
`movieFile` for the quality name and dropped `mediaInfo`, `path` and `size` from
the same dict, and Plex's listing carries `Media`/`Part`. No new requests.

**Why a new table.** `create_all` adds tables to a live database but never
columns, and the Docker CMD runs no migration. Same reasoning as `PlexCopy`.

## 2. Bytes per hour, against the library's own norms

**Problem.** Any threshold in gigabytes is wrong at both ends, and any per-season
figure is distorted by episode count and episode length.

**Change.** `analysis/bitrate.py` — rate is bytes per hour, bucketed by
resolution and codec; the baseline is the library's own median per bucket, with
spread taken as the median absolute deviation. Seeds apply only where there are
too few files to say anything.

**Why MAD, not standard deviation.** The outliers are precisely what is being
looked for. A distribution contaminated with a few remuxes drags a mean upward
far enough that the remuxes sit inside one sigma of it — a test pins twenty
ordinary files and four remuxes, where the mean would exonerate the remuxes.

## 3. Small files: the discriminator is runtime, not size

**Problem.** "Under a gigabyte" describes a short film, a truncated download and
a bad rip, and the worst available mistake is deleting the first.

**Change.** Compare the file's own duration with the runtime TMDB published,
both already stored. Far short of it → not the film, so all of it is reclaimable.
Full length but a fraction of its peers' bitrate → a bad rip, reported with
**zero** reclaimable because that disk stays in use until a better copy arrives.
Full length and genuinely short → left alone, and counted as cleared so the
number reads as considered. No published runtime → no verdict.

## 4. TV, and the season as the unit

**Change.** A Sonarr client, `shows`/`seasons`/`episodes`, and a new scan phase.
Sonarr is authoritative for the catalog and files; Plex for membership and for
*every copy it can see* — Sonarr tracks one file per episode, so a second copy on
disk is invisible to it.

**Why per season.** Air year is taken per season from the episodes rather than
from the series. Scrubs ran 2001–2010 and SpongeBob runs from 1999 into the
2020s: one answer per show is wrong for every long-running series, and it is the
air year that decides what the master can deliver.

## 5. Duplicate episodes, minus the two look-alikes

**Change.** Group by show/season/episode, rank by reclaimable bytes rather than
copy count. A multi-episode file is identified by path, so it counts once.

**The dangerous case.** Split parts cannot be separated by duration — two halves
of a sixty-minute episode and two copies of a thirty-minute one are both two
files of thirty minutes, and deleting the "duplicate" destroys the episode. Plex
models the distinction structurally (one `Media` is one presentation, its `Part`
entries are that presentation split across files), so `media_files.part_group`
records it and the answer is read rather than guessed.

## 6. HD or SD

**Change.** Three deterministic signals — what the season's master can deliver,
how much the picture rewards pixels, how attentively the show is watched.

**Two refusals, both pinned by tests.** `recognition` is never consulted: it
measures fame, and SpongeBob is one of the most recognised shows ever made, so
feeding it in inverts the decision. And no verdict is forced — thin evidence
returns "not enough to say".

**Asymmetric bar.** An upgrade only costs disk and can be undone, so one signal
justifies it. A downgrade destroys picture that cannot be recovered without
re-acquiring the show, so it requires low demand, low or absent attention, and a
known air year.

## 7. One ledger, three tiers

**Problem.** Five reports leave you to work out which to act on first.

**Change.** Every finding converts to estimated bytes reclaimable and lands in
one list, ordered by risk tier before size: nothing is lost → reversible → a
judgement call. A planner takes a target and returns the cheapest way to reach
it, cheapest measured in regret, and says plainly when the library cannot.

**Why the ordering is the substance.** Sorted by size alone the list routinely
proposes deleting something irreplaceable while a duplicate sits untouched
further down. Most of the disk comes back at tier 0, before any question of
taste.

## 8. Handbrake — gated here, executed by the host

**Change.** `ActionType.TRANSCODE`, and the golden guard generalised from "is
this a delete" to "is this irreversible". Sift never transcodes; an approved job
is claimed by an agent on the media box.

**Why the agent polls.** A hook would need that box reachable from wherever Sift
runs, which behind NAT it is not — the same trap `routes_config.py` already
documents, where "localhost" means the Sift server rather than your machine.
Polling also opens no inbound port.

**Guards.** Approval is checked at claim time, not trusted from job creation. A
staged instance hands out nothing. A reported success must bring its output size
and duration, because an unverifiable success is how a failed encode gets swapped
in for the real file.

**The re-grab guard.** Every applied downgrade writes the quality profile back to
Sonarr. Without it the next search fetches the larger file straight back, which
costs the picture *and* keeps the disk — worse than doing nothing.

## Gates

`ruff`, strict `mypy`, 341 tests, `npm run build`. Every new pin has a negative
control and each was mutation-verified: the implementation was broken, the test
confirmed red, then restored.

The TV ingest pin counts **lookups** rather than statements. The defect 2607.15.1
fixed was a SELECT per row; inserting new episodes genuinely requires writes, and
how a driver batches those varies by dialect. Ten episodes and a hundred must
cost the same number of lookups; a rescan of a hundred costs six statements.

## Not done here

Storage is read-only. Findings do not yet propose actions automatically — acting
on one still goes through the Junk screen and the action engine, one approval at
a time. Batch approval within tier 0 is deliberately left out pending a decision;
the per-item gate stands.
