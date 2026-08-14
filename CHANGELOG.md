# Changelog

Versioning scheme: `YYMM.major.patch`.

## 2607.25.0 — Fix the scan slowing to a stop, and the dial that could not move

The scan reached the Plex phase and then appeared to stop at 16%. Three separate
faults, and the earlier streaming fixes were what exposed the first one.

**The batch write got slower the further it went.** Episodes are written in
batches of 2,000, and each batch preloaded *every* show, *every* season and
*every* episode in the database. Batch fifteen of a thirty-thousand-episode
library therefore re-read twenty-eight thousand rows in order to write two
thousand. That is quadratic work introduced by the very batching that fixed the
original memory problem: the scan starts briskly, slows steadily, and ends up
looking stopped.

Measured on a 30,000-episode library, the last batch took **2.6x** the first;
scoped to the batch in hand it now takes **0.7x**. That measurement is on SQLite,
where the rows are local — against hosted Postgres every one of them crosses the
network, so the real effect is considerably larger. This is the third time that
gap has hidden something, which is why the pin is structural: a whole-table read
inside a per-batch write now fails the suite.

**The Radarr phase cost two round trips per film.** One `session.get` for the
film and one query for its ratings, inside the loop over every film — ten
thousand round trips on a five-thousand-film library. Both are now preloaded in
chunks, the same shape 2607.15.1 applied to the Plex phase and never reached
here.

**The dial genuinely could not move.** The percentage is derived from the phase
index alone — `(index + 0.4) / 9` — so every update during the Plex phase
produced the identical 16%, no matter how many episodes had been read. On a large
library that is the only thing on screen for many minutes, and it reads as a
crash. The sweep now reports how far through the section it is, using the size
Plex itself reports, and the dial interpolates within the phase. Only where a real
denominator exists: an invented one that climbs to 90% and stops is worse than a
number that never moves, because it also lies.

**The checklist was missing a phase.** `SCAN_PHASES` in the frontend listed eight
phases where the pipeline has nine — `sonarr` was absent — so that phase never
appeared while it ran, and the polling fallback divided by eight against the
server's nine. The two progress figures disagreed for the whole scan. A test now
reads the frontend list and compares it with the pipeline, so they cannot drift
apart again.

## 2607.24.0 — Six real bugs, and the measurements that found them

A continuous-improvement pass over the analysis and action code. It began as
performance work and turned up six correctness bugs, three of which could lose
data or misreport what happened to it.

**Every successful delete was being recorded as a failure.** The agent result
handler required an output size and duration before it would file anything as
done. Only a transcode produces those; a delete produces no new file. So every
delete the agent completed fell through to the failure branch, with the action
marked FAILED and an invented error attached. The reclaim feature emits nothing
but delete jobs, so this was all of them.

**The agent's trash could overwrite itself.** Approved deletes are moved to
`.sift-trash` rather than unlinked, which is the only thing standing between a
wrong approval and a re-download. It moved onto `trash/<basename>`, and
`shutil.move` replaces an existing destination silently. A transcode writes its
new encode out under the source's own name, so a later delete of that encode
landed on exactly the same trash path and erased the original it was protecting.

**Acting on a finding checked that paths existed, not that anything survived.** A
request naming every copy of an episode passed, because every one of those copies
exists. "Only the surplus goes" was a property of how findings were computed, not
of what the endpoint accepted. It is now enforced where it can be relied on.

**Two rankings were not deterministic.** `max(set(values), key=values.count)`
resolved ties by set iteration order, which for strings comes from Python's
per-process hash seed — so a season split evenly between two resolutions read as
either one, differing between runs over an identical library, on the path that
proposes irreversible downgrades. Separately, every ranking sort key was
non-total while none of the queries behind them specify an order: SQLite returns
rowid order, Postgres promises nothing, and the reclaim page shows only the first
500 findings, so equal-scoring items swapping places changes what you are shown.
Ties now break toward the lower resolution and the less efficient codec — both
make a proposed downgrade look smaller, which is the right way to be wrong about
a destructive suggestion.

**A service URL could point at cloud instance metadata.** Every major cloud
serves instance credentials from a link-local address with no authentication, and
Sift sends each service its stored API key. "Test my connection" could read the
deploy's own keys back through the health endpoint. Private ranges are
deliberately still allowed — Plex and Radarr live on a home LAN, and blocking
those would pass every attack test while making the product unusable.

**Scoring a library cost four database round trips per film**, the same shape as
2607.15.1, in the largest loop of the scan: 4.002 statements per film to 0.009,
with all 2,000 scores proven byte-identical before and after. The reclaim ledger
was rebuilt to select columns rather than ORM entities and to load shared data
once: 242ms to 132ms.

**Watch history is folded rather than collected.** History size tracks how much a
household watches rather than how much it owns, so a heavy viewer's is larger than
their library, and all of it was read into a list to be aggregated. Peak memory is
now the number of distinct titles rather than the number of plays.

Groundwork: `bench/` gains a seeded fixture and two benchmarks — one reporting
statements per film (the number that predicts hosted behaviour, since the bench
runs on SQLite where round trips are free), one reporting how much reclaimable
disk sits in the top of the ledger.

## 2607.23.0 — Fold watch history instead of collecting it

The third and last phase with the shape that killed the other two. History is
different in kind from the rest of a scan: its size tracks how much a household
*watches*, not how much it owns, so a heavy viewer's episode history is larger
than their library. All of it was being read into a list and aggregated once.

Nothing downstream ever wanted the rows. Both consumers immediately collapse them
into per-title aggregates, so the pages are now folded as they arrive and the
rows are discarded. Peak memory is the number of distinct titles rather than the
number of plays.

**The accumulators no longer grow with plays either.** Completions were kept as a
list to take a mean at the end — a running sum and count give the same number
without the list. Stream heights were kept as a list to take a median, which does
need the distribution, but a household streams at a handful of distinct heights
and watches episodes by the thousand, so counting them bounds it by the former.
The median walk is pinned against the definition it replaced, with mode and max
as the mutations it must reject: on a set of four 480s, three 1080s and two
2160s, the mode is 480, the max is 2160, and the answer is 1080.

**Tautulli got the same two pagination floors as Plex.** Its docstring already
claimed the read was memory-flat while accumulating every row; now it is.

## 2607.22.0 — Stream the Sonarr phase too, before it stalls the same way

The Plex fix in 2607.21.0 removes the first wall a TV library hits. The Sonarr
phase, one phase later, had the identical defect and would have been the next
one — a scan clearing 16% only to stop at around 38%.

**Same cause, larger payload.** Sonarr is read with one catalog call and then two
calls per show, each returning every episode and every file it knows about. All
of it was collected into a dictionary and written once at the end. That is a
bigger peak than the Plex sweep that already proved fatal, so there was no
reason to expect it to survive. Shows are now written every `SERIES_BATCH`, and
the phase reports how far through the library it is as it goes — two calls per
show against a remote Sonarr is minutes of silence otherwise.

**The sweep moved out of the batch, for the reason 2607.21.0 established.** It
was running inline on the assumption that Sonarr arrives whole. Once it does not,
a sweep decided from one batch deletes every batch either side of it: the
regression test for this leaves 4 files out of 40 when the sweep is put back
inside the loop.

**Three preloads were reading whole tables per batch.** Loading every season,
every episode, and every episode-backed `media_files` row was affordable when
each ran once per scan. Batched, they re-hydrate the same tables for every batch
— on a 30,000-episode library, hundreds of thousands of ORM objects built and
discarded. All three now name what they want: seasons and episodes by the shows
in hand, files by the paths in hand. Round-trip and hydration cost are both free
on the file-backed SQLite the tests use, so this is pinned structurally instead —
no read of `seasons` or `episodes` may go out without a filter.

**One quadratic loop.** Episodes were matched to seasons by walking the show's
whole episode list once per season. Grouping them first turns 10,000 comparisons
into 500 for a 20-season show — which is exactly the kind of show this feature
exists to look at.

## 2607.21.0 — Fix the scan dying partway through the Plex phase

A scan of a library with television in it stopped at the same point every time.
Not slowed — stopped, and always at the same place, which is the tell: a scan
that is genuinely slow moves eventually, and one that stops at an identical
point is being killed at an identical point.

**Root cause: the whole TV sweep was held in memory before anything was
written.** The episode read added to a list and the list was persisted at the
end. That is fine for films — a large film library is a few thousand records —
and quite different for television, where the same library is tens of thousands
of episodes each carrying full media detail. On a small hosted instance the
process is killed for memory before the first write. Nothing catches that: there
is no exception, the task simply ceases, and the run stays marked running for
ever. To the browser it is a bar that never moves again.

Episodes are now read as a stream and written every 2,000, so peak memory is one
batch instead of the library.

**The stale sweep had to change with it.** Reconciling `media_files` is a
delete-what-is-no-longer-there pass, and once the writes are batched, *any*
delete rule evaluated against a single batch gets duplicates wrong: the second
copy of an episode routinely arrives in a later batch than the first, so scoping
the delete to the batch's own episodes reads the first copy as vanished and
removes it. That destroys the exact evidence the duplicate report is built on,
in the act of recording it. Marking rows as they are written and sweeping once,
at the end, is the version that survives both — batching and duplicates.

**A long phase now says what it is doing.** It reported "running" and then
nothing until "done", so a twenty-minute sweep and a dead process looked
identical. It now names the library it is reading and the episode count as it
goes, which is also what makes a future stall diagnosable rather than a guess.

**Pagination is bounded three ways.** The container headers are a request, not a
guarantee; a server that ignores them answers every page with the first one, so
the offset advances and the data never does. The sweep now stops when it has
seen as many records as the section claims, and hard-stops at 2,000 pages
regardless. Neither floor may end the read early: a well-behaved server is still
paged all the way through, pinned by its own test.

## 2607.20.0 — A few shows you might want next

Missing gets a TV tab. **Eight suggestions, not twenty-four.**

Twenty-four film suggestions is a browse; twenty-four show suggestions is a
second job. A series is dozens of hours, so the useful answer is a handful you
might genuinely start — and a list nobody finishes reading is worse than one half
its length. The ceiling is 24 rather than unbounded for the same reason.

**Seeded by shows you finished, not shows you rate highly.** For films a rating
is a fair proxy for taste: watching one is a small commitment and most owned
films have been seen. Television is not like that. A library is full of series
acquired and never started, and letting those seed the search sends the whole
list somewhere you have already declined to go. Finishing episodes is the signal
that survives.

Agreement beats acclaim: three shows you finished pointing at the same title
outranks one pointing at something better reviewed. Each card says which of your
shows led there, so a suggestion can be argued with rather than only accepted or
ignored.

Nothing is requested or added from this screen — these are things to look at.

376 tests. New controls: a show you never started never seeds the list, one
nobody has rated is not suggested, and an absent TMDB says so rather than
leaving a blank panel to be read as a failure.

## 2607.19.0 — Television gets its own shelf

Library now has two tabs. Films and television are different shelves rather than
one list with a filter, because the columns worth showing differ and the
questions differ.

**Shows are never scored for removal, by decision.** A series is forty hours of
your life rather than two, and whether it *deserves* the space is not something
Sift has been asked to have an opinion about. So the TV tab shows what you hold —
seasons, episodes, size on disk, resolution, and when you last watched it — and
stops there. A test pins that nothing resembling a verdict appears in the
payload, so this cannot drift into a removal queue by accident.

Size is summed from the episode files rather than taken from Sonarr's own
figure, so it is the disk actually in use. That sum is one grouped query rather
than one per show: a TV library has an order of magnitude more episodes than a
film library has films, which is exactly where the 2607.15.1 mistake would hurt
most.

Every show library appears — Cartoons, Anime, Game Shows — with no per-library
setup, because nothing keys off the word "TV".

368 tests. New controls: a monitored show with nothing downloaded still lists at
an honest zero rather than vanishing, and the payload carries no score, band or
verdict field.

## 2607.18.0 — Which libraries Sift reads, and as what

Groundwork for treating television as its own thing rather than a data source
for the disk feature — and a correctness fix that was live before any of that.

**Home Videos were being read as films.** Plex types a Home Videos or Other
Videos library as `movie`, so Sift ingested family footage as a film collection:
into the removal queue, into the film counts, and — worst of the three — into the
bitrate baselines that every size verdict is measured against. A few hundred
phone clips are enough to drag the median for "1080p h264" somewhere meaningless
and quietly change what counts as an oversized film.

What separates those libraries is not their type but their **agent**. A library
with no metadata agent has no ratings, no cast, and nothing to match against
TMDB, so nothing in Sift can say anything useful about it. That is a fact about
the library rather than a guess about its name — "Home Videos" in another
language, or called "Camcorder", is caught the same way, and a real film library
called "Home Cinema" is not.

**Every show library is television, with no setup.** Cartoons, Anime, Game Shows,
Documentaries — nothing keys off the word "TV", so they were already ingested as
shows and stay that way.

Plex's type is a default rather than a verdict. Settings › Libraries lists every
library, what Plex calls it, what Sift will do with it and why, and lets you say
films / TV / ignore where Plex has it wrong.

One guard is worth naming because getting it backwards is silent: a library that
reports **no agent field at all** — an older Plex, a field that moved — is still
scanned. Inferring "personal media" from silence would make a scan read nothing
while looking exactly like a successful scan of an empty library.

362 tests. The new controls: the agent decides rather than the title, a missing
agent field does not drop a library, and a nonsense override falls back to Plex's
own answer instead of inventing a third kind.

## 2607.17.0 — Findings you can act on

2607.16.0 could tell you a show held the same episode twice and exactly how much
disk that cost. It could not remove it, and there was no button anywhere that
would. Seeing the problem was the whole feature.

**Nothing in Sift can delete a TV file, and nothing can be made to.** The only
writer that exists talks to Radarr, and the surplus copies duplicate detection
finds are precisely the files Sonarr never imported — manual copies, failed
imports, leftovers — so its API has no handle on them either. The path is the
only thing that does, and Sift runs where the paths are not.

So the mechanism is the agent protocol built for transcodes, generalised:

- `file_jobs` replaces `transcode_jobs`, which never held a row because nothing
  created one, and could not gain a `kind` column — `create_all` adds tables to a
  live database but never columns. The old table is left empty and unreferenced.
- `POST /api/storage/act` turns a finding into one audited action and the jobs
  behind it. It proposes; it does not do. Approval is still per item and dry-run
  is still the server's floor.
- **Paths are checked against the library snapshot before anything is recorded.**
  Without that this endpoint is a way to have a process with filesystem access
  delete anything on the box. A path Sift has never seen is refused.
- The paths come from the finding you were looking at rather than being
  recomputed, so what gets approved is what was on screen. The best copy of each
  episode is never among them.

**`tools/sift-agent.py` is the part that makes any of it real.** Standard library
only, runs on the machine holding the media, polls for approved work. It moves
deleted files to a trash folder rather than unlinking them — the approval gate
means you meant it, and the trash folder allows for meaning it and being wrong.
A re-encode is verified before the original is displaced: an encode that fails
halfway produces a file that plays, is much smaller, and is not the episode, and
every one of those properties reads as success.

349 tests. The new controls: a path outside the snapshot is refused, the kept
copy never appears in the surplus list, and a staged instance records your
approval while handing the agent nothing.

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
