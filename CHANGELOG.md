# Changelog

Versioning scheme: `YYMM.major.patch`.

## 2607.128.0 — The version check behind the Update button

Picked up from the stale-chunk work: this is the only thing that tells the owner
an update exists, and the button it feeds is what invalidates every chunk hash in
an open tab. So "there is an update" needs to be true when it says so, and "I
could not check" needs to stay distinguishable from "you are current".

The comparison arithmetic and the never-checked-and-offline case were pinned.
Everything between was not.

**The cache is not an optimisation, it is the difference between polite and
abusive.** The Settings page polls; without it every open tab on every instance
is a request to GitHub. `force` exists to get past it, because somebody who has
just updated wants the new number now rather than in fifty minutes.

**A failure after a success returns the answer already held**, and — the part
that needed its own control — **does not clear it**. Clearing on failure would
return the stale answer once and `None` for every check after, which is the
banner-flicker the fallback exists to prevent, delayed by one request.

**A fork checks its own repository.** Otherwise it reports itself permanently out
of date against somebody else's release cadence, and the Update button offers to
install a stranger's code. A *blank* override falls back to the default, because
an empty environment variable is how a deploy platform represents "unset" and
taken literally it builds a URL with no repo in it.

### One mutation came back green and the test says so

GitHub serving an error page is a 200 with HTML in it, which parses to nothing.
Two guards independently stop that wedging the check for an hour — `if version:`
on the write and `cached is not None` on the read — and either alone is
sufficient. Removing both turns the test red. It now pins the recovery rather
than claiming to protect one line, and is named for what it checks.

Seven mutations run; six red at the expected test.

`services/updates.py` 86% → **100%**.

## 2607.127.0 — The audit result, honestly qualified

The layout audit now records *which build it ran against*, because the first
recorded run did not and the claim was wrong because of it.

That run rebuilt the frontend partway through, so its four passes tested two
different builds: the early ones had the size-formatter fix and the later ones did
not. The neon screenshots still showed `0.0 GB` while the report said clean across
all thirty screen-theme combinations. Nothing was broken — the *claim* was.

Re-run properly against **2607.122.0**, a clean build of merged `main` with the
server restarted onto it and nothing touched during the run:

- No horizontal page overflow.
- No text clipped without an ellipsis or a `title`.
- No literal `undefined`, `NaN`, `[object Object]` or `Invalid Date`.
- **No console errors at all** — the stale-chunk error the previous run produced
  was self-inflicted, and is now handled on its own terms besides.
- All three themes verified applied on every screen.

Seventeen findings remain, every one a touch target on the phone pass, all already
written up as waiting on a decision. The skip link is among them and is fine: it
is keyboard-only and only visible while focused, so it is never a tap target —
noted so it is not mistaken for an open item.

The lesson is in the doc: build once, restart, then run.

## 2607.126.0 — A wedged browser tab must never stall the scan

`ScanHub` sits between the ingest pipeline and every open browser tab. The
pipeline `await`s `publish_progress` **on the event loop it is scanning on**, so
anything that can block there blocks the scan itself — and a browser tab is not a
reliable reader. A backgrounded tab is throttled, a suspended laptop reads nothing
at all, and a closed one does not say so until a write fails.

The socket's auth gate was covered. What happens once it is open was not.

**The load-bearing property**: each subscriber's queue is bounded at 100 and
written with `put_nowait` under `suppress(QueueFull)`. Frames past the bound are
dropped on arrival. Unbounded, one backgrounded tab is a memory leak; blocking,
one is a stopped scan. Dropping progress frames is the right trade — they are a
picture of a moving thing and the next one supersedes the last. Pinned by
publishing a thousand frames to a subscriber that never reads, each under a
one-second `wait_for`; the blocking version fails on the first.

The negative control is separate and necessary: an unbounded queue would also
never block, so "it did not hang" proves nothing on its own. The bound is asserted
at exactly 100, and the frames kept are the *oldest* — worth knowing, because a
subscriber that resumes sees the start of what it missed and then a jump, not a
smooth tail.

Also pinned: publishing to a scan nobody is watching is a no-op rather than a
`KeyError` (the ordinary case — a CLI scan, or a browser that has gone, and this
path runs on every frame of every unwatched scan); each scan hears only its own
progress; every subscriber to one scan gets the frame, because two tabs open on
the same scan is ordinary rather than an edge; the last reader leaving forgets the
scan, or the hub accumulates an entry per scan for the life of a process that runs
for weeks; **one of two readers leaving keeps the other subscribed**, which
dropping the whole scan on the first unsubscribe would silently break; and
unsubscribing something never subscribed is harmless, because the socket handler
unsubscribes in a `finally` that runs even when the connection failed first.

Progress is published with `asdict`, so a field added to `ScanProgress` reaches
the UI without a second edit — the kind of drift that otherwise shows up as a dial
that stopped moving. All seven fields asserted, not a chosen subset.

Six mutations run, all six red at the expected test.

`api/ws.py` 87% → 91%. The four lines still uncovered are the socket's send loop,
which needs a real connection rather than the hub.

## 2607.124.0 — The shadow scorer can now be looked at

`GET /api/junk/shadow-diff` has existed since the v2 scorer did, is fully
schema'd, and — as of 2607.105.0 — thoroughly tested. **Nothing in the frontend
consumed it.** No `api.shadowDiff()`, no type, no page.

So the one decision it exists to inform — cut the live scorer over to v2, or
don't — rested on a tool nobody could open. That is the same shape as
`/api/duplicates`, which was built and unconsumed until the Storage page arrived.

Settings → Scoring now carries a **Shadow scores** panel, directly under the
threshold sliders it belongs beside.

It reports the summary as **three separate outcomes, never one**. v2 being
*stricter* means it would queue films the live scorer keeps; *gentler* means it
would spare films the live scorer flags. Those are opposite risks, and a single
"40 disagreements" says nothing about which one you are taking. *Abstained* is
neither — it is v2 explicitly declining to answer, and folding it into either
direction reports an opinion the scorer refused to give.

Each row shows the disagreement as a **direction** (`junk → keep`, `90 → 10`) plus
which P-rule fired, because a pair of numbers without the arrow does not say who
moved.

Three deliberate restraints:

- **It fetches nothing until it is opened.** A whole-library comparison on every
  visit to Settings, for a panel most visits are not there for.
- **"Nothing compared yet" and "the two scorers agree" are different sentences.**
  They look identical if you only print the disagreement count, and they mean
  opposite things: *the scorer is ready* versus *the scorer has never run*.
- **There is no "switch to v2" button, and that is the point.** The cutover is a
  separate, considered act. A button here turns "look at the evidence" into "act
  on it", which is the opposite of what a shadow eval is for. The panel says so
  in as many words, and a test asserts the button's absence.

Seven mutations run, all seven red at the expected test.

### And an open tab surviving an update

The same browser run threw `Failed to fetch dynamically imported module` on
`/ask`, which I had caused by rebuilding the frontend under a running server.
That is not only a test artefact: **every page is a lazy import, and pressing
Update on Settings is a supported in-app action.** Any tab open across an update
hits exactly this on its next navigation.

The route boundary already caught it and kept the shell alive — but its primary
button was "Try again", which re-renders the same dead import and fails
identically, every time. The one button that can work sat second.

A stale chunk is now recognised as its own failure (matching Chrome's, Firefox's
*and* Safari's wording — one vendor's string leaves the other two with the useless
button), reloads itself **once**, and if that does not fix it says *"Sift has been
updated — this tab is running the previous version"* with only the button that can
help. The once-guard matters: a half-finished deploy or a proxy serving a stale
index would otherwise spin the reload forever. When `sessionStorage` throws —
private windows, blocked site data — it shows the error rather than starting a
loop it cannot stop.

Seven more mutations, all seven red.

## 2607.122.0 — The layout audit, committed

The browser pass that found the `0.0 GB` formatter and the silently-ignored theme
is now a script in the repo rather than something reconstructed each time, and its
findings have somewhere to live: `docs/BROWSER_QA.md`.

`npm run audit:layout` drives a real browser over all ten screens at 1440×1000 and
390×844, in dark, light and neon. It checks the four things jsdom structurally
cannot see — horizontal page overflow, text clipped without an ellipsis or a
`title`, literal `undefined`/`NaN`/`[object Object]`/`Invalid Date` on screen, and
console errors — and writes a screenshot per screen per theme for the part no
script does. It exits non-zero on a finding, so it can gate a release.

It also **asserts the applied theme on every screen**, because the harness bug
that surfaced the preference-validation defect made three whole theme passes render
the default palette while reporting success. That cannot happen quietly again.

The `undefined`/`NaN` check is the one worth naming: four mismatched test fixtures
have now shipped a page rendering the string `undefined` past a green suite, and
this is the check that would have caught every one of them.

Current state is clean on all four checks across all thirty screen-theme
combinations. Two things are recorded in `BROWSER_QA.md` as **waiting on a human**
rather than changed unilaterally, because control sizing and typography are design
decisions: a handful of 16px-tall inline controls (two of them adjacent on an
Activity row, which is the geometry that gets mis-tapped), and the Junk header
wrapping a figure away from its unit.

**Also removes `frontend/qa-run.mjs`**, which a `git add -A` swept into 2607.119.0
by accident. It was this script, at the repository root, before it had a home.

## 2607.121.0 — A 40 MB file was reported as "0.0 GB"

Found by looking at a rendered Storage page, which is the only way it could have
been: jsdom has no opinion about whether "0.0 GB" is a sensible thing to print, so
every unit test in the suite was happy.

There were **six copies** of the size formatter across the app and five of them
went straight from bytes to `(bytes / 1e9).toFixed(1) + " GB"`. Anything under
about 50 MB rendered as `0.0 GB`.

That is not a rounding nicety on this screen. Samples, trailers, truncated
downloads and `.partial` leftovers are *by definition* small — and they are the
entire tier-0 category, the one the page recommends acting on first because
nothing is lost. **The one screen whose job is to report sizes could not name the
sizes of the files it most needed to describe**, and a seeded 40 MB sample showed
`0.0 GB` beside the words "safe to delete".

One formatter now, in `lib/format.tsx` beside the answer formatter that was
already there: TB above a terabyte, GB above a gigabyte, whole MB above a
megabyte, KB below that, and an em dash for absent — never `0 KB`, which reads as
a real measurement of an empty file. Precision scales with the unit: the second
decimal of a terabyte is a real 10 GB, while a decimal below a gigabyte is three
digits nobody reads on a row that is one of two hundred.

### A stored preference was untrusted input

The same browser run surfaced a second one, by way of a bug in the harness. It
wrote `"dark"` — JSON-quoted, where the app stores raw — and **three entire theme
passes rendered the default palette while reporting success.** `read()` cast
whatever was in `localStorage` straight through, and an unrecognised value lands
on `data-theme` where it matches no CSS rule at all: the app renders the default
while Settings shows the stored name as selected. Silent, and impossible to
explain from the screen.

`read()` now validates against the allowed set, which is the working decision
already recorded for `Library`'s stored sort — applied where the same failure was
actually observed rather than reasoned about.

Six mutations run, all six red at the expected test.

## 2607.120.0 — How the engine is built, which nothing checked

`_resolve_url` was pinned. What `make_engine` does with the URL once it has it was
not, and both branches carry a setting that fails silently rather than loudly.

**Hosted Postgres gets `pool_pre_ping` and a recycle window.** Neon scales
connections to zero, and a pooled connection to a database that has gone to sleep
surfaces as an error on the *next* request rather than the one that idled. Without
these the first page load after a quiet period is a 500 — intermittent,
unreproducible on a warm instance, and exactly the shape of bug that gets blamed on
the app. Inspected on the engine rather than by connecting, so it needs no Postgres
and no driver.

**SQLite does not get them**, and that is a separate assertion rather than an
afterthought: a single `create_engine` carrying both option sets would satisfy the
first test while taxing every local session with a query per checkout.

**Foreign keys are enforced per connection.** Every `ON DELETE CASCADE` in the
schema depends on that pragma. Without it a deleted film leaves its scores, copies
and media files behind — and the tests that rely on the cascade would pass against
a database that never cascades.

**A pooled connection can be reused on another thread.** `check_same_thread=False`
is what lets the pipeline marshal database work onto a worker thread, which is the
whole reason a scan does not block the event loop.

### Two mutations came back green, and one of them was my test's fault

The thread test opened its connection *inside* the worker thread, which never
trips SQLite's check at all — it passed with `check_same_thread=True`, proving
nothing. It now opens one on the main thread, returns it to the pool, and checks
the same connection back out from the worker. That mutation is red.

The other stands: the `if url != "sqlite://"` guard is not what stops an in-memory
database using WAL. SQLite refuses WAL for `:memory:` on its own, so removing the
guard leaves the test green. The guard avoids a pragma that would do nothing, and
the test pins the journal mode each database actually ends up in rather than
claiming to protect the line.

Five mutations run; four red at the expected test.

`db/session.py` 82% → 84%. The modest jump is the honest number: the Postgres
branch was one uncovered line and everything else in the module was already
exercised by the suite.

**Flagged:** the remaining eight uncovered lines are `session_scope`, in its
entirety, and it has **no callers anywhere in the codebase** — every session is
opened through `factory()` or `in_thread` instead. Left in place and named here
rather than deleted: removing working code is the owner's call, not a test
sweep's, and writing tests for it would be covering something nothing runs.

## 2607.119.0 — The Settings tabs that change behaviour, and 80% frontend coverage

`Settings.test.tsx` covers the destructive and identity-bearing parts — the
unreadable-credentials banner, the password change, the dry-run switch, the
factory reset. This covers the tuning, which was the largest single gap left.

**The threshold preview.** The sliders move a number nobody can hold in their
head; the preview is the only thing that turns "junk cutoff 70" into "this would
flag 412 titles", and it has to arrive before the save rather than after a
re-score. A failed preview clears the count rather than leaving a stale one, and a
stale count is worse than none — it describes a setting that is no longer
selected, which is the one thing the panel exists not to do.

**The rescan schedule** puts the choice back when the save is refused. The chip
highlights immediately, which is right; what it must not do is keep highlighting a
schedule the server never accepted, because the owner walks away believing a
rescan is booked and none is. The chips are also disabled until the current
setting is known, or a click would save a schedule chosen against nothing.

**The Radarr add defaults** stay off the page entirely when Radarr has nothing to
offer — two empty selects imply a choice that does not exist, and the historical
default still applies. An unset profile is sent as `""` rather than `Number("")`,
which is `0`, which is a real profile id Radarr would reject.

**The poster cache** cannot be cleared when already empty, and re-reads its size
afterwards rather than assuming zero: the server decides what survives a clear, and
printing a number it was never told is the page inventing one.

### One test was vacuous and was rebuilt

The failed-preview control asserted that nothing was on screen after a preview
that *always* failed — there was never a stale value to clear, so removing
`setPreview(null)` left it green. It now lets a preview land first and breaks the
next one. (It also needed `fireEvent.change` rather than `userEvent.type`: arrow
keys do not move a range input under jsdom, so the typed keystroke fired no change
event and the second preview never happened.)

Eight mutations run, all eight red at the expected test after the rebuild.

`Settings.tsx` 56% → 76%.

**Frontend coverage is now 80.7% statements and 82.2% lines**, up from 66% at the
start of this pass — the target set when the sweep began.

## 2607.118.0 — What the Library remembers, and what it refuses to

`Library.test.tsx` pins the paging failure — a dropped page that used to vanish
without trace. This covers the rest.

**The test harness could not render a page at a route.** Several pages read their
filters straight off the query string — a deep link from the Dashboard, a search,
`?tab=tv` — and `renderPage` always mounted at `/`. There was no way to render one
in the state a link actually puts it in. It now takes an optional route.

**View and sort survive navigation, and an unrecognised stored value falls back.**
Somebody sorting by size is working through their largest files; coming back to
alphabetical after opening one title restarts that job. But `localStorage` is
writable by anything on the origin and survives upgrades that rename a sort field,
and a stored value taken on trust goes into the query string and comes back 422 —
a blank library with no explanation.

**The empty state tells two different stories.** "Run a scan to populate the
library" is useless advice to somebody who has a full library and mistyped a
title, and running one is the most expensive thing the app does. A search that
found nothing offers to clear the filters instead.

**The section select hides when there is one section**, because a select with one
option is a control that cannot do anything sitting in the row where the controls
that can are.

**Paging stops at a short page**, or the sentinel keeps firing at the bottom of a
finished list and the server is asked for page after empty page. **And a failed
page is not re-requested** while the sentinel stays on screen: without the
`pageError` guard the observer retries continuously — a request storm against a
server that is already refusing, with nothing on screen changing.

### One mutation came back green, for the second time in the same shape

Replacing `.catch(() => setSections([]))` with a rethrow leaves the "survives the
section list failing" test passing — exactly as the Activity page's scan-list
catch did. An unhandled rejection in a detached promise inside an effect never
reaches the render. Both catches keep the console clean; what protects the page is
that the two fetches are independent. Recorded as a working decision so the next
test of this shape claims the right thing.

Eight mutations run, seven red at the expected test.

`Library.tsx` 72% → 85%.

## 2607.117.0 — The write-back that stops a downgrade being undone

`SonarrClient.set_quality_profile` is the piece the design notes call
non-negotiable, and none of it had run. Its own docstring states the reason: a
season left pointing at a high cutoff is re-fetched by Sonarr's next search, so
the space comes back and is quietly spent again. **Applying a downgrade without
writing this back is worse than doing nothing** — it costs the picture and keeps
the disk.

Four properties, all of which fail quietly rather than loudly:

- **Dry run is the default, and a staged change reaches no network at all.** This
  is a write into the automation that manages the library, so it takes the same
  floor as the delete path: the caller opts *into* the live write, and one that
  forgot the argument stages.
- **The whole series object goes back.** Sonarr's series endpoint is a whole-object
  PUT — everything absent from the payload is taken as the new value, so sending
  only the changed field is how a write-back silently unmonitors a show or blanks
  its path.
- **The caller's copy is not mutated.** The payload is built with a spread rather
  than by assigning into the dict it was handed; mutating in place would leave the
  caller believing the change had applied even when the write was staged or failed.
- **A refused write raises.** A downgrade whose write-back failed must not look
  like one that applied — that is exactly the state the guard exists to prevent,
  and swallowing the error would create it deliberately.

Plus the boundary edges: a non-list answer from any of the four read endpoints is
an empty list rather than a crash mid-scan (a proxy, a login page and an error
body all arrive as valid JSON of the wrong shape), an unreachable Sonarr is a
status rather than an exception, and the API key never appears in a health message.

And Overseerr, which had two calls and no tests: a movie request sends
`mediaType`/`mediaId`, and health probes `/api/v1/status` rather than inheriting a
default — a client that probed the wrong path would report every working Overseerr
as down, and the add button would silently fall back to Radarr.

Seven mutations run, all seven red at the expected test.

`clients/sonarr.py` 77% → 100%, `clients/overseerr.py` 77% → 100%.

## 2607.116.0 — What the Junk queue does after you decide

`Junk.test.tsx` already pins the moments where the screen could say something
untrue about a *removal*. This covers the moments where it could say something
untrue about what is **stored**.

**A Keep that failed to save rolls the row back.** The row is marked kept
immediately, which is right — the screen should feel instant. What it must not do
is leave that mark standing when the write failed: the owner moves on believing a
title is protected and the next scan puts it straight back in the queue. The bulk
path rolls back per row and names the title, because "some titles failed" does not
tell anybody which one is still unprotected.

**Undoing a staged removal does not touch the Keep override.** Only a Keep holds
server-side state. A reset that always cleared the override would silently strip
protection set on the Library page, as a side effect of changing your mind about
something else entirely.

**The sort choice persists, and the default is score.** A disk purge is a session,
not a click — but score is the safety-relevant order and has to be what an empty
`localStorage` gives you, rather than whatever was last used.

**Re-running the AI review leaves the selection alone.** Re-running the
*explanation* of a queue is not a reason to re-tick the dozen titles somebody just
spared; losing it means starting a two-hundred-candidate pass again. And when no
provider is configured the message says the reason is the deterministic one — the
review is an explanation, never a verdict, and reporting it as `via deterministic`
invites reading it as a judgement.

**The sort fixture was vacuous and was rebuilt.** The Matrix was both the higher
score and the larger file, so the two sort orders were identical and the test
could not tell them apart. The Matrix now scores higher while Toy Story is the
bigger file, which is the disagreement the size sort exists for.

Eight mutations run, all eight red at the expected test.

`Junk.tsx` 61% → 85%. Frontend crosses 78% statements / 79.8% lines.

## 2607.115.0 — The score on the home screen, and the cache that made tests lie

`Dashboard.tsx` sat at 56%. The library-health score is the first number anybody
sees, and the page's own comment calls it "deterministic, auditable" — start at
100, subtract named deductions, show every one. None of that had a test.

**The junk deduction is a share of the library, not a count.** Fifty junk
candidates in a hundred titles is a different problem from fifty in five thousand,
and a raw count scores them the same. It is also capped at 40: uncapped, a library
that is 90% junk deducts 72 points for that alone and leaves no room for anything
else to register.

**An empty library scores 0, not 100.** With no titles there are no deductions, so
a naive `100 − 0` tells somebody who has never scanned that their library is in
excellent health.

**Unconfigured is not unreachable.** The page comment says so and now a test does:
a service that is set up but momentarily down does not earn a "connect it" card. A
card that appears every time the box is off teaches people to ignore the panel,
and the panel is how real problems surface.

**Actionable queues sort above setup cards.** Reviewing a junk queue changes the
library today; connecting Tautulli is housekeeping. Ordered the other way the
actionable item is below the fold.

**Staleness needs twice the interval, and needs an interval at all.** With the
rescan interval at zero, `hoursSince(finished) > interval * 2` is true for every
snapshot ever taken and the warning is permanent on any install that has not set
one. The negative control is deliberately nine hours against a six-hour interval,
not three: three is under the interval *and* under twice it, so it would pass
against either threshold and prove nothing about the "twice". One skipped rescan
is a laptop that was asleep; two is a snapshot worth doubting.

### The cache that made tests lie

`useStatus` and `useHealth` share results through two module-level maps, which is
what makes the window work — and it means they outlive anything that mounts and
unmounts, including a test. The second test in a file was reading the first one's
data for the length of the TTL and passing for the wrong reason. `resetSharedCache()`
is now exported and called from `beforeEach`. It is also the right thing to call
when the session identity changes, since the cache would otherwise hand the next
caller a status read taken under the previous token.

**A fourth mismatched fixture.** `COUNTS` invented `watched`/`unwatched` and
omitted `collections`, `watch_records`, `watched_titles` and `actions_pending`;
`as never` meant nothing complained. Corrected.

Eight mutations run, eight red at the expected test — one of them only after the
staleness control was rebuilt, because the first version passed against both the
real threshold and the mutant.

`Dashboard.tsx` 56% → 86%. `hooks.ts` 91% → 90% statements but 96% lines.

## 2607.113.0 — Two scan phases that had never run under test

Two whole phases of the ingest pipeline were uncovered, for the same structural
reason in both cases: **the test doubles answered them with nothing.** The shared
Tautulli double returned an empty list for episode history, and no test in the
suite ever passed a TMDB client at all — every scan under test ran with
`tmdb=None` and returned from the first line of that phase.

The result was 137 uncovered lines in `ingest/pipeline.py` that looked like dead
code and were not: they are three network-shaped loops, each with its own budget
and its own failure policy.

### Episode watch history

This is one of the three axes that decide whether a show needs to be in HD, and
none of it had been exercised. Now pinned: plays attach to a show by Plex's
grandparent rating key, which is the only identifier an episode play carries that
names its show; history is fetched as a **separate** request per media type, not a
filter over the movie sweep (`get_history` defaults to `media_type="movie"`, so a
caller that forgot the argument would silently aggregate film plays into the show
columns); and plays for a show Plex no longer has are dropped rather than attached
to whichever show came first.

Three judgements about absent data, each of which matters because a downgrade is
the irreversible direction:

- **A play with no reported resolution leaves the height unknown**, not SD.
  Defaulting it to 480 would tell the suitability rules a show is watched in
  standard definition when nothing of the sort is known.
- **A play with no completion percentage is not a play at 0%.** Counting it as one
  drags the mean down and reads as a show nobody finishes.
- **The stored height is the median, not the maximum.** One 4K play on a borrowed
  television must not argue that the whole show needs a 4K master.

Plus the round-trip pin the Plex phase already has: `_persist_show_watch` preloads
every show with a rating key in one statement and matches in memory. Measured at
under ten statements for 201 shows; a lookup per show is free on SQLite and is the
difference between a phase that finishes and one that looks hung on Neon.

### The TMDB phase

Enrichment is capped by its budget and a budget of zero asks TMDB nothing. One
title TMDB refuses is skipped and the rest of the budget is still spent — a phase
that aborted on the first bad id would leave a whole library unenriched because of
one deleted TMDB entry.

Canon resolution makes **two different calls for two different qualities of
evidence**: an IMDb id is an identity and resolves exactly, a title and year is a
guess and goes through search precisely so it reads as one.

And the distinction the module docstring already claimed but nothing checked: **a
miss is a counted attempt, not a verdict.** TMDB answering "no such film" today
does not make a title un-canonical — the attempt is counted and the entry stays
pending until the ceiling. An *exception* is not a miss at all: counting a network
error against the attempt ceiling would mark real canon unresolvable during an
outage, for reasons that have nothing to do with the film.

### Two mutations came back green and the tests now say so

- The `if self.tmdb_enrich_limit > 0` shortcut is not what makes a zero budget
  fetch nothing — `_tmdb_targets` passes the limit to a SQL `LIMIT`, and `LIMIT 0`
  returns no rows. Removing the `LIMIT` *does* turn the test red. The shortcut
  saves a round trip.
- Removing **all three** `if self.tmdb is None: return {}` guards leaves the phase
  passing. Every TMDB call sits inside a best-effort `except Exception`, which
  swallows an `AttributeError` on `None` as readily as a network failure. The
  guards stop pointless database work and an error log per pending entry; they are
  not what keeps the scan alive.

In both cases the test docstring records what the mutation showed rather than
claiming to protect a line that is not load-bearing.

Eleven mutations run in total; nine red at the expected test.

`ingest/pipeline.py` coverage 84% → 95%, `ingest/normalize.py` 87% → 91%.

## 2607.110.0 — "No activity yet" was the wrong sentence

`Activity.tsx` calls itself the trust surface in its own header, and sat at 55%.
The two things it must never say were already pinned — that nothing happened when
the fetch failed, and that a staged action was executed. Everything else was
untested: the scan history, the type filters, the payload, and the growing window.

**Writing the filter test found a third wrong sentence.** The empty state was
keyed on the *filtered* row count, so filtering to deletes on a log containing
none of them rendered "No activity yet" — which on this screen reads as *your
delete was never recorded*. The two cases now have different words, and the way
back out of a filter is a button rather than working out which chip to press.

The scan panel is how anyone finds out why a scan produced the numbers it did,
and none of it had run. Pinned: duration and totals; a run still going shows "…"
rather than a duration computed from a null finish time (which is `NaN`, and
"NaNm NaNs" beside a running scan reads as a crash); phase detail stays folded
until asked for; a failed run shows its error and says plainly that it has no
phase detail rather than showing an empty box; and the panel is absent entirely
when nothing has run, because an empty "Scans" panel on a fresh install reads as
a fault.

Also pinned: the payload stays hidden until asked for and carries `dry_run`
itself, not only in the pill above it — the pill is a summary and the payload is
the record, and a record has to stand on its own. And "Show more" appears only
when the server filled the window it was given; on a partial page it would fetch
the same rows again.

### One mutation came back green and the test says so

Replacing the `.catch(() => undefined)` on the scan-list fetch with a rethrow
leaves the "a failed scan list does not take the log down with it" test passing —
an unhandled rejection in a detached promise inside an effect never reaches the
render. What protects the log is that the two fetches are independent; the catch
keeps the console clean. The test pins the log surviving, which is the property
that matters.

Eight mutations run; seven red at the expected test.

`Activity.tsx` 55% → 92%.

## 2607.108.0 — The half of Storage that answers "I need 500 GB back"

`Storage.tsx` sat at 54%, and the covered half was the confirm dialog. The
uncovered half was the target planner and the tier board — which is the point of
the screen.

**Two fixtures were inventing field names, and the compiler was told not to
mind.** `Storage.test.tsx` mocked `LedgerResponse` as `{items, total_bytes,
by_tier}` and `MovieSizeResponse` as `{items, excess_bytes, undersized}`. The real
types carry `total_reclaimable`/`tiers` and five named counts. Both were cast with
`as never`, so every summary figure on the page rendered the string `undefined`
and seven tests passed anyway. This is the third time a fixture that did not match
its type has produced a green suite over a page rendering nothing (see 2607.99.0
on `ShowSummary`), so the first new test reads all five headline numbers
precisely and asserts that the string "undefined" appears nowhere.

Now pinned:

- **The target is typed in gigabytes and asked for in bytes.** A nonsense or empty
  target asks for nothing at all, rather than sending `NaN` — which would either
  422 or, worse, read as zero and return a plan that frees nothing while looking
  successful.
- **A plan that cannot reach the target says so.** Silently returning the best
  effort would let somebody free 200 GB believing they had freed 500.
- **The plan names the riskiest tier it has to reach.** "8 GB, and you will have to
  make a quality judgement for it" is a different offer from "8 GB, nothing is
  lost", and the number alone hides that.
- **Tiers are ordered safest first, always.** Sorted by size instead, tier 2 would
  usually lead — and the ordering *is* the claim the page makes about being
  dependable.
- **The staged/live pill assumes staged when it cannot find out.** A failed
  settings read that defaulted to "Live" would tell somebody their deletes are
  real when nobody knows either way. Wrong in the safe direction is the only
  acceptable wrong here.
- **A finished scan refetches rather than reloads**, so scroll position and
  anything half-armed survive.

And the television sections, none of which had run: only seasons the server
actually judged `bloated` are listed (ranking on total bytes would put every long
season at the top of a list headed "heavier than their peers"); the per-hour rate
is shown beside the total, because "60 GB" is not an accusation and "5.00 GB/h"
is; and a season that disagrees with itself is reported separately, since fixing
one odd SD episode among HD ones usually *costs* space and has no place in a queue
ranked by bytes reclaimed.

Eleven mutations run, all eleven red at the expected test.

`Storage.tsx` 54% → 82%. Frontend 74.5% → 76.1% statements, 76.0% → 77.6% lines.

## 2607.107.0 — The library-kind form, and a message that reached nobody

`SectionsForm` is the highest-consequence form in the app and sat at 31%
coverage. It decides what Sift reads as a film — and Plex calls a Home Videos
library a *movie* library, so a wrong answer here puts family footage into the
removal queue, the film counts, and the size baselines every verdict is measured
against. The backend route behind its Save button was returning a 500 on every
attempt for as long as it existed (fixed in 2607.101.0) and nothing noticed,
because neither side had a test.

Now pinned: both facts appear side by side (what Plex calls it *and* why Sift
disagrees); the current choice is `aria-pressed`, not merely styled; Save is
disabled until something changes and sends nothing before it is pressed; a failed
save keeps the edit so pressing Save again retries it; and — the property the
code comment already explained — **the whole map is sent, not only what the user
touched.** An override set back to Plex's own answer still has to be transmitted
or the previous one sticks on the server, and the screen goes on describing a
setup that is not in effect.

Also separated: a Plex that cannot be read and a Plex with no libraries. Both
rendered as "nothing here" before; they are different problems and only one of
them is worth going to look for.

### A message written to state nothing rendered

`ShowSuggestions` was at **0%** — not one line had ever run under test. Writing
the first failure test found the bug: the `catch` set `detail`, but the render
only consulted `detail` once `items` was non-null. A failed request therefore
left the loading skeleton shimmering permanently and the reason reached nobody.

Fixed by giving the message somewhere to go, and by passing the server's own
explanation through rather than a fixed string — a missing TMDB key is worth
saying out loud.

### Relative time

`lib/time.ts` is small and was at 36%, but it writes the sentence under "Last
scan", every line of the activity log, and the `hoursSince` comparison that
decides whether the app offers to scan again. Pinned: the unit fits the distance,
the hour boundary is 48 h rather than 24 (a scan that ran yesterday afternoon
reads better as "36 h ago" than "2 d ago"), and a clock ahead of the browser reads
"just now" rather than "-5 min ago".

`hoursSince` deliberately makes the *opposite* choice and returns a negative
rather than clamping: it feeds `>=` comparisons where a clamp to zero and a
genuine "just scanned" would be indistinguishable.

### One mutation came back green and the test says so

Removing the `Math.max(0, …)` clamp in `relativeTime` leaves the future-timestamp
test passing — any negative minute count is also less than 1, so the "just now"
branch catches it first. Removing both does turn it red. The clamp is
belt-and-braces; the test claims the output, not the line.

Six mutations run; five red at the expected test.

Frontend coverage 71.7% → 74.5% statements, 73.2% → 76.0% lines.
`SectionsForm.tsx` 31% → 96%, `ShowSuggestions.tsx` 0% → 100%, `time.ts` 36% →
100%.

## 2607.105.0 — The eval that decides the cutover was itself unverified

`shadow_diff` is how the v1→v2 scoring cutover gets decided. Its own docstring
calls it "the only honest eval that exists for taste", because it runs on the
owner's real library rather than on cases chosen to prove a point. It had no
tests at all, which meant the numbers on the one screen that decision rests on
were unchecked.

Twelve pins, covering the four things it can get quietly wrong:

**Who is compared.** Only films *both* engines scored. A film v1 scored and v2
did not is an absence, not a disagreement, and counting it reports drift no
engine ever claimed.

**Which direction.** keep→junk is v2 being stricter, junk→keep is v2 being
gentler, and anything→`insufficient` is v2 declining to answer. `insufficient`
is not a rung on the keep/borderline/junk ladder, so an ordering comparison
against it is meaningless — ranked naively it sorts below `keep` and every
abstention would be reported as v2 wanting to *keep* a film it has explicitly
refused to judge. That is the number the cutover is read from.

**Which band counts as v1's.** The stored band, not a recomputation. A film
scored 45 under a borderline cutoff of 40 was borderline when v1 judged it;
recomputing under a later cutoff of 50 relabels it and manufactures a
disagreement neither engine ever had. Rows written before bands were stored still
fall back to the thresholds, so the diff does not silently shrink to the newest
scans.

**Which films reach the page.** Ranked by gap size, then truncated — not the
reverse. Cutting before ranking returns whichever films came back first, an
arbitrary sample presented as "the worst disagreements", which is precisely how
a shadow eval lies.

**The stated cost was wrong and now is not.** The docstring claimed two
statements. Measured: three — two whole-table score reads plus one chunked title
hydrate, identical for a five-film and a four-hundred-film library. The claim was
off by the hydrate it forgot; on hosted Postgres, where every statement is a round
trip, that is the number worth stating accurately.

**Two fixtures were vacuous and were rebuilt.** The tie-break test used ids
1/2/3-style values, and a set of small ints iterates in sorted order anyway — it
passed with the ordering removed entirely. It now uses ids whose set order
genuinely differs, and asserts that in the fixture so it cannot silently rot. The
limit test had ascending ids and descending gaps, so truncate-before-sort returned
the same three rows; the gap now grows with the id, which makes the two orders
opposites.

One mutation is honestly green: removing the tmdb_id tie-break alone leaves the
order stable, because `sorted(shared)` upstream already delivers it. Removing
*both* turns the test red. The pin is on the contract, not on which of the two
mechanisms happens to be carrying it, and the test says so.

`analysis/junk.py` coverage 81% → 93%.

## 2607.104.0 — One dead seed must not kill the list

`tv_recommend.suggest` is the async half of the show recommender: for each show
you actually finished, two TMDB lookups, merged. `rank` and `anchors` have their
own tests; this had none, and it carries two properties the pure functions cannot
express.

The first is written in a comment beside the `except` that exists for it: **one
dead seed must not kill the list.** A seed whose lookup fails should cost its own
contribution and nothing else — a library with six watched shows should not lose
all six suggestions because one of them 404s. Pinned, along with the client being
closed even when a seed throws, which is a `finally` nothing was checking.

The second is the merge. A show that two of your favourites both point at is a
better suggestion than one either points at alone, and it should say so.

**Two mutations came back green, and one of them was a real gap.** Asserting that
both reasons appear on the card leaves the *weight* accumulation untested —
replacing the running total with the latest anchor's passes, because with a single
candidate there is no ordering to get wrong. There are two candidates now, one
named twice and the other better on its own merits, so only the added weight can
put the doubly-named one first.

The other green is honest and recorded rather than papered over: deleting the
`if not seeds: return []` early exit changes nothing, because an empty seed list
means the loop body never runs and `rank({})` is already empty. It is an
optimisation that avoids constructing a client, not the guard — the same shape as
the Radarr shortcut in the version before this. The test now asserts the thing
that *is* load-bearing: nothing is asked of TMDB at all.

Five mutations red, one honestly reported green.

## 2607.103.0 — Two endpoints that exist to degrade well

`/api/settings/radarr_options` offers real root folders and quality profiles so
the add defaults are a choice rather than a guess. **Every failure path in it
returns empty** — unconfigured, unreachable, misconfigured — because the UI reads
empty as "defaults apply", and a 500 there would break a Settings page somebody is
visiting precisely because their connection is broken. The unreachable case is the
common one: Radarr configured, the box off.

`/api/settings/test/{service}` probes live and then **drops the cached health
sweep**. That second half is the one worth guarding. The dots poll a fifteen-second
cache, and somebody who has just fixed a URL and pressed Test is watching those
dots — a stale sweep tells them the fix did not work.

Both pinned, with a negative control that a *reachable* Radarr offers its real
choices. Without that, every one of these tests would pass on an endpoint that
returns empty unconditionally, which is the failure mode of every
graceful-degradation test.

**One mutation came back green and the test now says so.** Deleting the
`not enabled` shortcut does not break anything: the call falls through to
`RadarrClient(...)`, which raises `ClientError` for a missing base URL, and that is
caught a few lines below. The shortcut is an optimisation that avoids building a
client at all, not the guard — so the test covers the behaviour rather than
claiming to protect a line that is not load-bearing.

Three mutations red, one honestly reported green.
## 2607.102.0 — What a repeated delete answers

The status codes on the destructive path, which is where a client's retry logic
reads them. A refusal that arrives as a 500 looks transient and gets retried; a
double-submit that arrives as a 200 tells the person it worked twice.

The 403 for an unapproved delete — the golden guard, surfaced over HTTP — was
already pinned. The rest of the mapping was not.

**Executing the same action twice** now has a test. A double-click on Approve, or
a client retrying a request whose response it never saw, must not read as another
successful removal: 409 says *this already happened*, which is the only answer
that lets a client tell a retry apart from a fresh action. Unknown ids on approve,
reject and execute answer 404 rather than falling through to a 500. And a rejected
action cannot then be executed — rejection is a decision, and a later execute must
not quietly overturn it.

**The first version of the repeat test proved nothing**, which is worth recording
because it looked right. It executed a delete for a film Radarr does not manage,
so the *first* call was already a 409 for an entirely different reason and the
second one matching it meant nothing at all. The film now exists with a
``radarr_id``, so the first call genuinely succeeds and the second genuinely
conflicts.

Four mutations, all red.

## 2607.101.0 — Two scans against one library

A scan writes the whole library snapshot. Two at once against one database is the
thing `/api/scan` exists to prevent, and the guard had no server-side test. The
frontend has a pin saying the *client* refuses to start a second, which proves
nothing about a second browser tab, a curl, or the wizard's silent auto-start
landing at the same moment as the dashboard button.

Pinned now, in both directions. A second start **joins** the running scan rather
than racing it, and launches nothing new. A resume that names a *different* run
while one is live is refused with a 409 — that is not a join, because a resume
names a specific run and running it beside another is two scans. Resuming the run
that is already live is a no-op rather than an error, since that is what a
reconnecting client does.

The other half is the orphan. A `RUNNING` row whose task died with the process
would wedge scanning forever if it were treated as live — and on a host that
restarts on deploy that is an ordinary state, not a rare one. It is retired to
`INTERRUPTED` and a fresh scan starts.

**One test made a claim it could not support, and now does not.** It said the
`expunge` before returning an ORM row was load-bearing — that without it FastAPI
would touch attributes on a closed session. Mutation says otherwise: removing
both expunge calls leaves the test green, because the attributes are already
loaded and nothing lazy-loads. The call is defensive rather than load-bearing, the
test now says so, and it covers the property that actually matters — that the
response serialises — instead of guarding a line it does not.

Four mutations red, one honestly reported green.
## 2607.100.0 — Correcting a Plex library mapping was a 500

`/api/config/sections` decides what each Plex library *is* — films, shows, or left
alone. Its own docstring says why that matters: Plex calls a Home Videos library a
*movie* library, so without an override family footage is read as films, into the
removal queue, the film counts, and the size baselines every verdict is measured
against.

**Correcting it never worked.** `set_sections` called
`runtime.rebuild(request.app)`, and `rebuild` takes the `AppState`, not the app.
`request.app` has no `session_factory`, so every attempt to fix a mapping raised
`AttributeError` and returned a 500. The three other `rebuild` call sites in the
same file all pass `state`; this one was the odd one out.

**Strict mypy passes this**, which is worth recording: Starlette types
`request.app` as `Any`, so the type checker has nothing to object to. A call that
crashed on every invocation type-checked cleanly. That is what the endpoint having
no tests at all was hiding.

The planner underneath (`ingest/sections.py`) was well covered — including the
Home Videos case. The HTTP layer around it had nothing, which is exactly the seam
where this lived.

Pinned now: Home Videos and Music are left alone by default while Films and TV
Shows are read; an override reaches the **live settings object the next scan
reads**, not merely the response, since "takes effect on the next scan" is a claim
about the rebuild rather than about the write; and a Plex that is unconfigured or
unreachable returns a status rather than a 500 — the setup wizard calls this before
anything is connected, and a laptop away from home hits the second case daily.

Two bugs in the tests themselves, both instructive. Mutating the fixture's
settings after `create_app` leaves the app holding the old copy, so the
"unconnected" case was asserting against a Plex it still thought was connected.
And reaching for live state needs the same accessor the routes use.

Four mutations, all red.

## 2607.99.0 — Six dots that were only a colour

The connection-health row is the app's most compressed piece of state: six 8px
dots standing in for six services. Compressed to the point where **colour was
doing all the work** — green ok, amber auth-failure, red offline, grey not
configured, and no other difference between them.

This project's own standard is glyphs rather than colour alone. Six dots that
differ only in hue are six identical dots to a colour-blind reader. The `title`
and `aria-label` on each one already covered screen readers and hovering, but
somebody scanning the header with the mouse elsewhere got nothing — and being
glanceable is the entire reason the row exists.

Shape carries the state now, alongside the colour rather than instead of it:

* **ok** — a filled circle
* **auth failure** and **offline** — filled, and square-ish. Amber was the state
  most at risk: it is a problem, and a round amber dot is indistinguishable from
  a round green one to anyone who cannot see the hue.
* **not configured** — a hollow outline. Nothing is wrong and nothing is
  connected, which an empty ring says without relying on grey-versus-green.

Radius rather than a glyph because a glyph is illegible at 8px and a shape is not.
Checked the way it should be checked — screenshotted the row through a greyscale
filter, where the hollow rings and the filled square read apart immediately.

Five mutations, all red, including "drop the colour, keeping only shape": shape is
the addition, not the replacement. Most people read these by hue and always will.
## 2607.98.0 — Three inputs a keyboard user could not find

The browser audit came back clean across all ten screens. Then a grep found three
controls with **no visible focus state at all**: the global search box, the Ask
question field, and the Radarr defaults inputs in Settings.

`focus:outline-none` is how you stop the browser's default ring clashing with a
rounded design. It is also how you make a control invisible to anyone navigating
by keyboard — you tab into the field and nothing on screen says so. WCAG 2.4.7,
Level AA.

**axe cannot see this**, which is why the audit passed. Focus appearance depends
on computed styles in a state the page is not in while being scanned. It is a
grep-shaped problem and it wanted a grep.

Two of them take the ring the rest of the codebase already uses. The search box
does not: it is a transparent field inside a bordered pill, so a ring on the input
would draw a second outline a pixel inside the first. That one goes on the wrapper
with `focus-within`, where the border already is.

`focus-visible.test.ts` now refuses any `focus:outline-none` without a visible
replacement on the same element or its wrapper — with a negative control checking
the rule matches a real offender and not a real fix, because a lint-shaped test
whose regex matches nothing passes beautifully.

Confirmed in a browser afterwards: thirty tab stops, every one of them visible.

Three mutations, all red.

## 2607.97.0 — Three accessibility failures a browser found

The project's standards ask for keyboard and touch, colour-blind-safe glyphs and
reduced motion. Nothing had ever audited against them. Ran axe over all ten
screens of a real instance and found three violation types, two of them
**critical**.

**Two form controls with no accessible name.** The Library's section and sort
selects, and the Taste Profile's weight sliders. A select with no name is
announced as its current value and nothing else — "combo box, Films" — because
the visible text is the option, which says what is *selected* and never what is
being chosen. The sliders were worse: several to a page, each announced "slider,
0.5", indistinguishable from one another. This is the same failure as the
unlabelled login inputs fixed a few versions ago, in three more places.

**Text below the contrast floor.** `--fg-3` is the caption colour on every card
and row, rendered at 10–12px, which WCAG counts as small text and holds to
4.5:1. Dark sat at **4.17:1** and light at **3.22:1** — the second is a real
readability problem rather than a marginal one. Fixed with the smallest
hue-preserving shifts that clear it; the neon theme already passed at 4.82:1 and
is untouched.

**Pills that inverted on the light theme.** The tint is `color-mix(colour 18%,
transparent)`, which over a dark surface gives a dark wash under bright text and
works. Over a *light* surface it gives a pale wash under the same mid-tone text,
and all three tones measured **2.2–2.8:1**. Text and tint are now separate
tokens — `--keep-ink`, `--borderline-ink`, `--junk-ink` — resolving to the tint
colour on dark themes, where nothing changes, and to darkened variants on light.

**And one that only a browser could see.** After all that, the junk pill still
failed at **4.48:1** — by 0.02. My own arithmetic had said 5.83:1, because I
composited the tint over the *page* background while the pill is actually drawn
on a card. The browser measured the real backdrop. Eight points brighter on the
ink clears it without touching `--junk`, which is also a border and a score
colour.

Both halves are now permanent. `frontend/src/test/contrast.test.ts` measures
every pairing as arithmetic in the unit suite, including pill tints over both
surfaces — with a negative control that checks the maths against the ratios WCAG
publishes, because a contrast test measuring the wrong thing passes just as
easily as one measuring the right thing. `npm run audit:a11y` runs the full
browser sweep against a live instance and exits non-zero on any finding.

The unit test was too strict at first and failed on five pairings the app never
renders — `--fg-3` on `--bg-3`, which backs dots and rings and carries no text.
Narrowed to the two surfaces text is actually drawn on rather than changing the
palette to satisfy a test I had invented.

A mutation also showed the stylesheet test could not see which token the *component*
picks, so pointing `Pill` back at the tint colour would have undone the whole
light-theme fix while leaving every assertion green. That is pinned separately now.

All ten screens report zero. Seven mutations, all red.
## 2607.96.0 — The download that promised to match the screen

`routes_export` states the promise plainly: the CSV "shares the exact
filters/sort of `/api/movies` … so the download always matches the visible set".

That promise lives in one `useMemo` reading the same `buildQuery` the list reads,
and nothing checked it. **A download that quietly differs from the screen is worse
than one that fails** — the file looks right, and the difference is only
discoverable by counting rows.

Pinned now, including that paging stays out of it: the file is the whole filtered
set, capped server-side, not the sixty rows currently rendered. Two mutations
cover both halves — building the export from a different query, and letting the
page number into it.

The quick filters are pinned too, and the assertion that matters is the negative
one: each filter asks for what it means **and nothing else**. A stray `in_plex` on
the kids view would silently hide every kids film not yet owned, and the view
would look entirely correct while being wrong. "Below cutoff" deliberately does
carry `in_plex`, because an upgrade for a film nobody has is not an upgrade — it
is a suggestion, and that is the Missing page's job.

And changing a filter returns to the first page, without which a filter change
lands at the offset of the list you just left and the top of the new one is never
shown.

`Library.tsx` 71.6% → 72.3%. Five mutations, all red.
## 2607.95.0 — The audit log, and the setting that turns motion off

Two surfaces where being wrong is quiet.

**Activity is the only screen that answers "did that file actually go?"**, and
both wrong answers cost something: believing a file is gone when it was staged
means re-running a removal that already worked; believing it was staged when it
is gone means not looking for it until much later. The distinction is one
ternary, and nothing checked it. Pinned now, in both directions — a staged action
says so, a live one does not say it — along with the autonomy label that records
whether a person had to agree, and the `dry_run` flag surviving into the payload
rather than living only in the pill. The pill is a summary; the payload is the
record, and somebody reconstructing what happened months later reads the second
one.

**`reduceMotion` does not animate anything.** It writes `data-reduce-motion` onto
`<html>` and `tokens.css` collapses the transitions. The setting is only as real
as that attribute, and `lib/prefs.tsx` had no tests at all — so somebody who
turned motion off and kept getting animations had no way to tell whether the
toggle, the attribute or the stylesheet was at fault.

It now pins that the attribute is written, that it says `"false"` rather than
going absent (the selector is `[data-reduce-motion="true"]`, so removing it works
today and breaks silently the moment anyone writes a rule for the other case),
and that the preference survives a reload — asserted by mounting a second
provider, which reads storage exactly as a fresh page load does.

The OS-level `prefers-reduced-motion` is honoured separately by the stylesheet.
Checked rather than assumed, and left alone.

Also pinned: a malformed accent is ignored rather than painting the app with
`undefined` — a half-typed hex reaches that code on every keystroke of a colour
field — and clearing one *removes* the custom property instead of setting it to
empty, which would override the stylesheet with nothing.

`lib/prefs.tsx` 46% → 89%, `Activity.tsx` 37% → 55%, frontend overall 69% → 71%.
Ten mutations, all red.

## 2607.94.0 — A dialog that showed twenty of forty-five and said forty-five

The confirm dialog for removing surplus episode copies lists the paths it is
about to act on. It listed **twenty of them** and stopped, with no indication
that there were any more.

The heading says the real number — "Remove 45 surplus file(s) from Scrubs?" — so
somebody reading carefully could work it out. Somebody scanning sees twenty paths
under a heading that says forty-five and takes the twenty for the list. This is
the dialog where that reading removes files.

A truncation nobody is told about is the same failure as no truncation, only
quieter. It now counts what it left out: *"and 25 more not listed here"*.

Pinned with the mutation that matters most: **the display cap must never become a
scope cap.** If twenty ever leaked from the list into the request, twenty-five
duplicate files would still be sitting on disk after a removal that reported
success — and the report would be the only evidence, which is to say none.

Also pinned that the counter stays away when there is nothing to count. A dialog
that always warns is a dialog nobody reads.

`Storage.tsx` stays at 54% — the dialog was already exercised and this added one
small branch to it. The honest figure, since the value here is the fix rather
than the percentage. Three mutations, all red.
## 2607.93.0 — What the card actually says, in a browser

Booted a real Sift with a 400-film library and drove every screen with Chromium.
The API errors it turned up were all poster 404s from an instance with no TMDB
key — expected, not bugs. Looking at the pixels found something no test could.

**The Missing card's caption was truncated to uselessness.** It carried four
facts — tier, director, genres, runtime — in a line that lives on a 108px card,
and rendered as `Essential · Joel Coe…` on every single card: the tier, half a
name, and nothing else. The genres and runtime added two versions ago were
*never visible to anybody*.

Nothing in the suite could see it. The string was composed correctly and then
clipped by CSS, and jsdom has no layout, so the assertion that the caption
contained all four facts passed while the browser showed one and a half.

The caption now carries the two things the other lines do not already say —
**one genre and the runtime**: what kind of film, and how long an evening. The
title line already has the year. The reason line names the director whenever the
director is *why* the film is there, which is most of the time and far more
useful than a bare name. Tier is a filter chip and the sort order of the list.

Where there is no personal reason, the reason line now reads *"Directed by …"*
rather than falling silent — that is the fact people recognise a film by, and it
is the only place a director appears now.

**Two genres was also too many.** "Comedy, Drama · 116 min" is twenty-three
characters where the card holds about twenty, so the runtime clipped off every
card that had two. Found by asking the rendered page which lines had
`scrollWidth` past `clientWidth`, rather than by counting characters and hoping.
Afterwards the only lines still clipping are long film titles, which is what a
poster grid does and what the tooltip is for.

The cards now read: *Barton Fink · 1991 / Comedy · 116 min / You own 3 films by
Joel Coen*. Three lines, three different facts, all of them legible.

## 2607.92.0 — The switch that makes every delete real was one click

Covering the Autonomy tab found the gap it exists to guard.

**Switching writes to live had no confirmation.** One click on "Live — send to
Radarr" and approving any removal deletes the file for good. The warning that says
so appeared only *after* the switch had already happened.

The app confirms deleting one film. It did not confirm the setting that decides
whether deleting films is real. That is the wrong way round: every other
destructive step here is gated one item at a time, and this is the one that makes
all of them count.

Going live now asks, in the same dialog every other irreversible action uses. It
also says the thing people most need to hear at that moment — per-item approval
still applies; what changed is what approving *means*.

**Only that direction asks.** Going back to staged makes nothing happen that was
not going to happen anyway, and a confirmation on a safe action is not free: it
teaches people to click through the ones that matter.

Pinned along with it: neither button is offered before the current mode has been
read, since a button that acts on a state it has not loaded can flip the setting
to whatever it assumed; the live-mode warning stays; and cancelling changes
nothing.

Factory reset was already confirmed properly, and is now pinned too — including
that the "keep thumbnails" button actually keeps them. Two buttons, one endpoint,
one boolean: getting it backwards silently discards a poster cache somebody asked
to keep, which is not a disaster and is exactly the kind of thing nobody notices
for months.

`Settings.tsx` goes from 37% to 56%; the frontend overall to 65.5%. Eight
## 2607.91.0 — A statement budget for every screen

A performance sweep across every read endpoint the UI calls, on a library-sized
dataset: 4,000 owned films, 300 shows, the full 25,000-entry canon.

**It came back clean.** Nothing costs more than eight statements, nothing is doing
an N+1, and continuing an endless list costs one statement where starting one
costs three. Recorded as a finding rather than quietly dropped, because a sweep
that only ever reports problems is one nobody can calibrate.

So instead of a fix, the measurement became a guard. `test_endpoint_cost.py` puts
a **statement and byte budget on every read endpoint**, and the numbers are the
observed costs plus a little headroom rather than round numbers picked to pass.

This is the read-side counterpart to `test_scan_cost.py`. Hosted Postgres bills
for round trips and for bytes moved; the tests run on file-backed SQLite where
both are effectively free, so an N+1 introduced in a route is invisible to every
other test in the suite and surfaces weeks later as "the app got slow" on somebody
else's database. Version 2607.15.1 exists because exactly that happened on the
write side.

**Two things the negative control caught, which is the point of having one.**
`/api/health` was given a budget of two statements and costs zero — it probes
external services and has no business reading the database at all, so the budget
is now zero, which is a stronger claim than "small". And the continuation of an
endless list was budgeted at two against an observed one; a mutation that puts the
hidden-title counts back on every page slipped through at two and fails at one.
A budget with slack in it is decoration.

Verified against a real N+1 injected into the suggestions route: the guard turns
red.
## 2607.90.0 — Two URLs that skipped the guard

A security pass over the whole app, since it holds Plex, Radarr and TMDB
credentials and is meant to be reachable from the internet. Most of it came back
clean, and the two things that did not are the same thing twice.

`reject_unsafe_base_url` refuses a URL pointing at cloud instance metadata, and it
lives in `BaseClient.__init__` so that every client gets it without anybody having
to remember. **Two paths build their own httpx client and so never pass through
it:**

* **the Ollama provider.** `routes_config` already guards this exact URL before
  probing it, with a comment saying why — it "builds its own httpx client, so it
  was the one path that could be pointed at 169.254.169.254 and used as a
  reachability oracle". The provider that calls the *saved* URL on every scan had
  no such check, so a URL that failed the connection test could still be saved and
  then used.
* **the deploy hook.** A stored URL the server POSTs to on request is an SSRF
  primitive. Blind and authenticated, so not the worst of its kind — but the guard
  exists so that "refuse to send credentials to the metadata endpoint" is true
  *everywhere* rather than nearly everywhere. A control with a hole in it is worse
  than no control, because everybody stops checking.

Both now go through the same function as everything else, and both keep working
for the setup people actually have: a local Ollama on `127.0.0.1` or a LAN
address, and a real Render hook.

**What the rest of the pass found: nothing.** Recorded because a security review
that only ever reports findings is one nobody can calibrate. No endpoint echoes a
stored secret back — probed live against `/api/config`, `/api/settings`,
`/api/health`, `/api/status`, `/api/system/version` and the decisions export.
Nothing logs one. Passwords are PBKDF2-SHA256 at 240,000 rounds; sign-in is rate
limited at five failures a minute; session tokens last thirty days and asset
tokens fifteen minutes. Tokens that ride in a query string — posters, CSV, the
scan socket — are accepted at *asset* scope only, so one recovered from an access
log cannot reach the API, and the decisions *import* correctly refuses asset
scope. No raw SQL, no `dangerouslySetInnerHTML`, CORS limited to the dev server.

Four mutations, all red.
## 2607.89.0 — The client every screen goes through

`lib/api.ts` was at 42%, and the parts that were untested are the two mechanisms
behind the bugs that started this whole thread: the **timeout** that turns a hung
page read into a visible error, and the **401 handling** that drops a dead session
back to the login screen instead of leaving every panel quietly broken.

Both are code that only ever runs when something has already gone wrong — which
is exactly when nobody is in a position to debug it.

Pinned now, each with its opposite:

* the stored session token is sent, but **an explicit credential wins** — on a
  fresh install a stale token in storage would otherwise be sent in place of the
  deploy token, and the rejection looks exactly like the deploy token being wrong;
* a 401 clears the token and announces the death **once** — but a 401 from
  `/api/auth/*` does not, because signing someone out for mistyping their
  password clears the very token they are trying to replace, and a 500 is not a
  session death either;
* the server's own explanation survives rather than being replaced by the status
  text, and a **non-JSON error body** (a proxy's HTML 502) does not throw a
  second, different error on top of the first;
* a request that never answers becomes *"Timed out waiting for a response"* after
  45 seconds, and the timer it set is **cleared** rather than left to fire against
  a request that already finished;
* a 204 returns nothing instead of being parsed as JSON.

Nine mutations, all red.

**One test's name was wrong and is now right.** It claimed to distinguish a
timeout from a caller cancelling; `ask` is the only call that takes a caller
signal and it sets no timeout, so it exercises the cancel path and not the
discrimination between the two. No call site currently passes both. The test says
so, and says which branch will need its own pin when one does.

`api.ts` goes from 43% to 54%; the frontend overall from 63% to 64%.
## 2607.88.0 — The TV list, at 2%

`ShowsList` is read-only, so nothing in it can delete a file. It is also the only
place the app states a number about television, and a wrong number is worse than
no number — somebody deciding what to remove reads "4.2 TB" and acts on it.

Pinned: the summary adds up episodes from what arrived but takes the shelf's size
and count from the server, which is the distinction between "this page" and "your
library"; a failure says so rather than rendering an empty shelf, because an empty
TV list means *you own no television* and that is a completely different statement
from *the server did not answer*; sorting and filtering ask the server rather than
reordering the page in place; "last watched" sorts newest-first, since ascending
would put the shows nobody has touched in years at the top of it; and a show
nobody has ever played reads **never** rather than "0 plays".

**The first version of the fixture was wrong, and every test passed anyway.** It
invented `episode_file_count`, `size_on_disk` and `quality` — none of which the
component reads — so every row rendered its size as "—" and its season count as
`undefined`, and seven green tests said nothing about any of it. The fixture now
matches `ShowSummary` field for field. A fixture that does not match the type is a
test of nothing in particular, and it is green, which is the dangerous part.

`ShowsList.tsx` goes from 1.9% to **94.4%**; the frontend overall to 65.8%. Six
mutations, all red.

## 2607.87.0 — Walking the whole thing once, as a person would

Every part of the Missing feature was tested. The lists have their own pins, the
affinity arithmetic has its own file, the ignore endpoint has its own suite. What
none of them proved is that the parts fit *together* — and **both bugs this
feature shipped with were integration bugs**, invisible from inside any single
piece:

* the API sent raw pillar tags as a film's reasons, because the route and the
  analysis disagreed about what `reasons` meant;
* the top-up ranked dead last, because the ranking and the top-up disagreed about
  what a *missing* score meant.

So there is now a walkthrough that goes through the HTTP API rather than the
services, and asserts what a person would actually notice: the list arrives
ranked by the shelf with a reason on the top card and metadata on nine rows in
ten; the reasons never name the built-in list; one director does not fill the
page; a refusal survives a re-read and can still be taken back.

**One of its tests could not fail, and now can.** The paging pin walks four pages
and asserts no title appears twice — and removing the id from the `ORDER BY`
leaves it green, because SQLite returns rows in a stable scan order whether or not
anything guarantees it. A test that cannot fail is worse than no test: it is a
claim nobody will re-examine. The property is now pinned *structurally* — the
compiled query's last ordering term has to be a unique column — and the
behavioural test says plainly, in its own docstring, what it does not prove.

Six mutations, all red.
## 2607.86.0 — The lists rebuild themselves, and ask before changing anything

The two shipped lists are derived from evidence, and **the evidence moves**. IMDb
publishes fresh dataset dumps daily, films get released, vote counts settle, and a
rating that was thin two years ago is not thin now. A list built once and never
rebuilt is a snapshot of whenever somebody last remembered to run the script.

`.github/workflows/refresh-lists.yml` now rebuilds both lists monthly.

**It opens a draft pull request; it never commits to `main`.** These files ship
inside the product, a rebuild can drop a title that was on the list last time, and
"a robot changed 7 MB of JSON" is exactly the change that wants a person to look
at it. The rebuilt files also have to pass the same tests as the shipped ones
before the PR opens — entry count, every entry tiered, ids unique, metadata
coverage, and the invariant that the two lists never overlap by IMDb id.

A 25,000-entry JSON diff is unreadable, so `tools/canon/diff_lists.py` writes the
PR body instead: what came in, what went out, what moved tier, and whether
metadata coverage held, with the most-voted examples of each. Dropped titles are
called out specifically, since anything there was on the list last time and its
removal is the change most likely to be wrong.

The generator is deterministic — the same inputs produce the same files — so
anything the summary reports is a change in the *evidence* rather than in the
rules. Verified by rebuilding twice from the same dumps and getting no diff.

`list_overrides.json` is the other half of the loop and the one place a judgement
call belongs. The generator never writes it, the workflow never touches it, and a
correction put there survives every rebuild. That is the whole shape: the machine
proposes from evidence, a person corrects by hand, and the correction sticks.
## 2607.85.0 — A README that describes the app that exists

The README still described Sift as reading "Plex + Radarr (plus Tautulli + TMDB)"
— no Sonarr, no Overseerr — and the Missing screen as "the validated canon minus
your shelf", which stopped being true three versions ago. It also never explained
the one thing most worth understanding: **how a recommendation gets chosen and
ranked**, which is the part that decides what somebody actually sees.

There is now a section for it, written to be read rather than skimmed: the three
sources that feed one list, the two shipped lists and where they come from, the
rule that AI supplies candidates and never verdicts, and the ranking that counts
reasons off your own shelf — with a worked example of a card, because "You own 5
films by Akira Kurosawa" explains the design faster than a paragraph about it can.

The project layout was stale in three places (`ai/` and `data/` were missing
entirely, `analysis/` and `services/` listed things that had moved), and the
list docs were not linked from anywhere.

Every claim in the file is now checked rather than asserted: the doc links all
resolve, every path in the layout block exists, the counts match the shipped data
files, and the AI providers named match `registry.MODES`.

## 2607.84.0 — The top-up was ranking last, which is the same as not existing

The affinity ranking shipped one version ago broke the thing it sat next to, and
the failure was invisible from anywhere except the surface it ruined.

`canon_affinity` is keyed on `imdb_id`. **Top-up rows have no IMDb id** —
discovery hands back TMDB ids, so a film found by the TMDB sweep or named by an
AI provider never gets an affinity row at all. With the sort using
`nulls_last`, a **tier-1** discovered film landed at position **25,000 of
25,001**: below every tier-4 title in the shipped canon.

The top-up exists so the list never runs out. It had been reduced to making the
count go up.

A missing score now means what it should mean — *this row has no reasons from the
library* — and the row ranks on its tier, which is exactly where a canon row with
no metadata ranks. The same tier-1 film now lands at position 2,215, among the
other tier-1 films, ordered by fame within them.

The tier weights now exist in two places: a SQL `CASE` that runs inside the query
and `affinity.TIER_POINTS` that runs in Python. They are the same statement, so a
test pins that they agree — nothing else would notice if they drifted.

**A bug in the first version of that test, worth recording.** It read
`_effective_score()` without the outer join it depends on, and SQLAlchemy quietly
made its own implicit join, so every row picked up somebody else's score and the
test read 4 where it expected 2. The helper now says in its docstring that it is
only valid inside a query that joins `CanonAffinity`.

Three mutations, all red.
## 2607.83.0 — Forty-seven films the exclusion list would have eaten

The two shipped lists are disjoint **by IMDb id** — zero overlap, by
construction, since the canon takes IMDb's `movie` and the exclusions take
`video` and `tvMovie`. Checked, not assumed.

By *title and year* they overlap 47 times, because a theatrical release and a
same-named TV movie can share a year: *Home Alone 2: Lost in New York*,
*Anastasia*, *Starship Troopers 2*. And title-and-year is not a hypothetical
path — it is the only key available for a candidate with no IMDb id, which is
exactly what TMDB discovery and every AI provider hand back.

So the discovery top-up would have quietly refused *Home Alone 2* on the grounds
that a different 1992 film of the same name went straight to video.

A contested title now resolves toward **keeping** it. The two errors available
here are not the same size: a wrong exclusion silently removes a good film from
every surface for ever and nobody can see that it happened, while a wrong
inclusion offers one bad suggestion that gets ignored in a second.

An IMDb id still decides on its own, unchanged — an id in the exclusion list is
an exact statement about that film, and the guard never sees a candidate that
resolved.

Four mutations, all red, including the one that resolves ambiguity the other way.
The property the whole design rests on — that the lists never overlap by id — is
now pinned too, because if a rebuild ever broke it the ambiguity above would stop
being about same-named films and start being a contradiction.

## 2607.82.0 — Recommendations that can say why

The Missing list was ranked `(tier, -votes, tmdb_id)` — the canon's judgement,
then fame. A defensible global ranking, and **the same ranking for everybody**:
it recommends the most famous unowned film in the strongest tier, over and over,
to a person whose library says plainly what they actually watch.

The ask was suggestions "sorted by what is suggested the most". The obvious
reading — count the sources vouching for a title — does not survive the data:
24,417 of the 25,000 entries carry exactly one source, so that ranking is a
near-universal tie broken by whatever comes next. The reasons are counted from
the shelf instead.

**A director already on the shelf is a reason. A genre the shelf is full of is a
weaker one.** Both are arithmetic over stored rows, both are facts about this
household, and both can be said in a sentence on the card — which matters,
because a recommendation nobody can explain is one nobody trusts. Cards now read
*"You own 5 films by Akira Kurosawa"* and *"Horror is 80% of your library"*.

Tier is folded into the score rather than left as the primary sort key. That is
the whole mechanism: leaving tier on top and affinity as a tiebreak produces the
same list as before with reasons written on it, which is a worse outcome dressed
as a better one. A tier-4 film by a director the owner clearly loves should
outrank a tier-1 film they have shown no interest in, and now does.

**One director must not own the whole page.** Measured, not feared: a shelf with
five Kurosawa films on it put **twenty-five consecutive Kurosawa films** at the
head of page one. Every one is a film the owner plausibly wants, and it is still
not a recommendation list — it is a filmography, and you have to scroll past all
of it to find out the list contains anything else. Each film after the first by a
given director now pays a small fixed toll: three lead instead of twenty-five, and
distinct directors on the first page went from 34 to 61.

Two supporting tables, both new rather than columns, because `create_all` adds
tables on a live database and never adds columns. `canon_metadata` holds the
genres, runtime and directors the lists gained in 2607.81.0. `canon_affinity`
holds the score and the words behind it, rewritten whole on every scan by a new
`affinity` phase — buying two more films by one director changes the score of
everything else they made, and working out which rows those are costs more than
recomputing all of them.

The reasons are **stored** beside the score rather than derived at read time. The
first version derived them, which added two aggregate statements to every page of
an endless list; the statement-count pins caught it immediately. Stored, they cost
sixty short blobs per page and always agree with the score sitting next to them —
a fresh reason attached to a stale score is the worse kind of wrong.

**Two fixes found on the way.** The API was sending raw pillar names (`cult`,
`imdb_wr`, `criterion`) as the reasons — meaningless to read, and exactly the
built-in-list provenance that is supposed to stay invisible. Tier claims now read
"Widely regarded as essential" and name no list at all. And the card crashed the
entire Missing page on a film with no director, which is not hypothetical: IMDb
records no genres for a few hundred canon entries, and a deploy serves the new
page against the old API for as long as the backend takes to roll. One card
without a director is a fine outcome; every other suggestion vanishing is not.

Thirteen mutations, all red.

## 2607.81.0 — The lists learn what the films actually are

Both lists carried a title, a year, a rating and a vote count. That is enough to
rank by fame and nothing else — no way to say *why* a film is being suggested, and
no way to filter by anything a person would actually think in.

They now carry **genres**, **runtime** and **directors**, at 98%, 98% and 99%
coverage. Everything comes from IMDb's official datasets, so the lists stay what
they have always been: derived from evidence, never hand-authored.

Two of those fields were already being read and thrown away. `read_titles` parsed
`runtimeMinutes` to enforce the featurette floor and then dropped it, and the
genres column sat one index further along the same row, untouched. Directors are
genuinely new work — a streamed pass over `title.crew` to collect director ids for
titles on either list, then a second over `name.basics` to resolve only those ids.
Neither file is held in memory; `name.basics` is 300 MB compressed and almost all
of it is people who directed nothing on either list.

**A bug found on the way.** The first version built its fact table from the titles
that survived the membership filters, which left 461 Criterion entries with no
genres at all — *Sherlock Jr.*, *Simon of the Desert*, *Zéro de conduite*. All
films that are in the canon on Criterion's word and are also under an hour long,
so the featurette floor had already dropped them before enrichment could see them.
Membership filters decide what belongs on a list; they have no business deciding
what is *known* about a title. Facts are now collected before any filter runs.

What remains uncovered is honest: 360 entries have no IMDb id at all (they arrived
from Criterion or the cult list by title alone) and 60 more are IMDb rows whose
genre column is genuinely empty, mostly experimental cinema.

Directors are capped at three. Anthology films list every segment's director, and
past a handful that stops being an answer to "who made this".

The pins are on the shipped files rather than a fixture, because the thing worth
guarding is a *file*: the generator takes `--crew` and `--names` as optional
flags, so a rebuild without them produces a perfectly valid canon with every
director silently gone. Four mutations, all red.

## 2607.80.0 — Which door opens, and an unlabelled front one

`AuthGate` decides four ways and only one of them shows the app. Getting any of
the others wrong either locks the owner out or lets someone in, and it was at 54%.

The pin that matters most is the **fresh install**. The API is open until an
account exists — that is how the setup wizard reaches it — so a successful
`/status` probe there proves nothing, and treating it as proof would drop a
brand-new, unauthenticated instance straight into the app with every endpoint
answering. The code already gets this right, with a comment saying why; there is
now a mutation that inverts it and a test that goes red.

Three more decisions, each pinned with its opposite:

* a **401** on `/status` drops to the login screen;
* anything else — a booting instance, a proxy hiccup — does **not**, because
  showing a login form the owner's password cannot get them past is worse than
  letting them through to a server that will tell them what is wrong;
* a **mid-session token death** (`sift:unauthorized`, which is exactly what
  changing the password fires) drops to login, instead of leaving every panel on
  screen failing with no explanation.

Sign-in failures now have pins too, including that a rejected sign-in **clears the
stored token**. Keeping a credential the server has just refused means every later
request carries something that cannot work, and the failures arrive one screen at
a time instead of at the login form, where the person is actually standing. The
three failure messages stay three: try a different password, wait, or go and check
the server are three different next actions.

**A real accessibility fix on the way through.** The username and password inputs
had placeholders and no labels. A placeholder is not a label: it is announced
inconsistently and it disappears the moment anyone starts typing, so a
screen-reader user on the front door had two unlabelled boxes and no way to tell
them apart. Both now carry an `aria-label`.

`AuthGate.tsx` goes from 54% to **91%**; the frontend overall from 62% to 63%.
Seven mutations, all red.

## 2607.79.0 — The bulk button, and the rule it was best placed to break

Per-item approval is the standing rule for anything that deletes a file: one
`Action` row per title, each individually approved and audited. A **"Select all
and approve (N)"** button is the single most obvious place for that to quietly
become one approval covering many files, and it had no test.

It does not break the rule — three titles are three proposals and three
approvals — and there is now a pin that says so, plus a mutation that approves
once for the whole batch and turns it red. A convenience for the person clicking,
not a different kind of write.

Two more, both about the moment it goes wrong. The bulk button **asks first**,
like every other removal on that screen. And a failure **stops the walk**: one
removal failing usually means the server or Radarr has gone away, and walking on
through two hundred more is not persistence, it is two hundred more ways to be
wrong. The toast names what happened; a mutation that swallows it turns the pin
red.

**And the dialog now says the number.** It read *"Approve removal of 3 title(s)?"*
— on the one dialog in the app that deletes files, where the count is the most
important word in the sentence and "(s)" reads as unfinished.

`Junk.tsx` moves 60% → 61%, which is the honest figure: what is left uncovered
there is rendering variants, and this change was about the destructive path
rather than the percentage. Six mutations, all red.

## 2607.78.0 — The fallback that carries a blocked scan

`lib/scan.tsx` carried a comment explaining its own design:

> A socket error/close is NOT the end — the poller below is the source of truth,
> so progress still completes even if the WS is blocked.

Nothing tested it. The file was at **22%**, and a websocket is the first thing a
corporate proxy, a tunnel, or a hosted platform's edge will drop. If the fallback
did not carry a scan on its own, the bar would sit still — which reads as a crash
and gets reported as one.

It does carry it, and there is now a pin that proves it: the socket opens, stays
completely silent, and the scan still reaches 100% off the poller alone. The pin
deliberately waits past the 1.5-second interval, because a shorter wait would be
satisfied by the single immediate poll and prove nothing about the loop.

Five more behaviours pinned, each one a way the panel could lie:

* a transient poll failure does **not** end the scan — a free-tier instance waking
  up returns errors for a few seconds, and treating one as terminal abandons a
  scan that is running perfectly well;
* the dial never goes backwards, because two sources write to the same number and
  they do not agree moment to moment;
* a terminal event ends the scan and names the error;
* a phase goes active when its event arrives;
* starting a scan while one is running joins it rather than racing a second one
  against the same library — which matters because the wizard auto-starts one
  silently and the dashboard button is right there.

`scan.tsx` goes from 22% to **91%**; the frontend overall from 57% to **62%**.
Six mutations, all red.

## 2607.77.0 — Proving it wasn't the form

The original report was "why are my keys not being saved?". That turned out to be
a server-side decryption problem — the key that decrypts stored secrets had
changed — and `ConnectionsForm` was never the cause. But it was at **38%**
coverage, and it is the only thing standing between a typed key and the database,
so "it wasn't the form" was a guess wearing the clothes of a conclusion.

It is a fact now: **82%**, with the save path pinned end to end.

The behaviour guarded hardest is the **blank field**. Blank means *keep what is
stored*, because a saved secret comes back masked and there is nothing to
re-type. Get that backwards and editing the Plex URL silently wipes the Plex
token and the TMDB key sitting untouched beside it — which, from the outside, is
indistinguishable from keys that were never saved at all. The mutation that sends
blanks for everything now turns that pin red.

Also pinned: typed secrets are dropped from component state after a save (the
fields re-render from the masked server response, so anything left behind is a
copy of a secret with no reason to exist); a failed save says so instead of
showing "Saved ✓"; Clear sends explicit empty strings, which is the one path
where an empty string is the message rather than the absence of one; and a Test
request that throws is reported rather than leaving the button in its resting
state, since the reading most people take from silence is "fine".

Six mutations, all red. Frontend overall 55% → 57%.

## 2607.76.0 — The password screen was telling you the opposite of the truth

I had measured backend coverage but never the frontend. It is 51%, against the
backend's 91%, and the worst file was `pages/Settings.tsx` at **11%** — the screen
where connection keys are entered, which is to say the screen the original "why
are my keys not being saved" report was about.

Covering it found a real bug, and not a cosmetic one.

**Changing your password said "Your sessions stay signed in."** Changing your
password *rotates the signing secret*, which signs every other device out. This
device survives only because the server hands back a replacement token and the
client stores it. The message was true of the old behaviour — the backend's own
docstring records that it used to keep every session alive — and the copy never
followed the change.

That is the worst possible direction to be wrong in. The reason anyone changes a
password on a reachable instance is that they think someone else has access, and
they were being told nothing had been revoked at the exact moment everything had.
It now says: *"Password changed. Every other device has been signed out; this one
stays in."*

The panel is pinned properly now: a mismatched confirmation and a short password
never reach the server, the typed passwords are cleared from the screen after a
success, and a rejected change reports the rejection — **in the failure colour**,
which is the only thing distinguishing the two outcomes at a glance and the one
part a mutation showed was doing no work.

`Settings.tsx` goes from 11% to 38%; the frontend overall from 51% to 55%.

## 2607.75.0 — The entry point nobody had ever run

`cli.py` was the only user-facing surface in the codebase at **0% coverage** — 70
statements, three commands, and no test anywhere that so much as imported it. "Does
`sift --version` work" was an open question.

It is at 92% now, and covering it turned up a real bug.

**`sift init` cannot work from a `pip install`.** It looks for `sift.toml.example`
three directories above `cli.py`, which resolves to the repository root in a source
checkout and to the interpreter's library directory in an installed one — and the
templates are not shipped inside the distribution or copied into the Docker image
either way. So in the container this project actually ships, the command fails.

It failed *gracefully*, with `sift.toml.example not found next to the package` —
a message describing a place the code had not looked. It now names the directory
it searched and says a source checkout is required. The underlying fix is a
packaging decision (ship the templates in the distribution, or add them to the
image) rather than a change to this function, and the image is configured through
the web UI rather than this command, so it is written down in `ENGINEERING.md`
instead of worked around.

The remaining uncovered lines are `serve`, which hands control to uvicorn and
blocks for ever, and `__main__`. Both are the right place to stop.

Seven mutations, all red — including "report success when the template is
missing", which is what the old code's shape invited.

**Also measured, and left alone:** a sweep of sixteen endpoints on a 25,000-title
canon and a 4,000-film library found nothing to fix. Worst case is 8 statements
(`/api/status` and the reclaim ledger, both genuinely aggregating from eight
tables — no N+1 anywhere) and the largest payload is 57 KB. The request path is
done; saying so is more useful than manufacturing another optimisation.

## 2607.74.0 — Somewhere to see what you set aside

The last release said the ignored list was readable and a decision could be taken
back. That was true of the API and false of the app: `GET /api/missing/ignored`
had no screen, and the only way back was an undo button on the card you had just
clicked, which vanished on reload. A promise with no way to keep it.

There is now a **Set aside** tab on Missing. It lists what you have passed on,
most recent first, each with a way back. "Remembered forever" was always a
promise made to the suggestion engine — nothing in there is ever proposed again,
by the built-in list, by TMDB or by any AI — and never one made against the
person using it. A decision that cannot be reviewed is not a decision, and on a
list of twenty-five thousand films a mis-click is a matter of when.

A failed read says so instead of showing an empty list, which would say every
decision you made is gone and read as good news. A film whose restore the server
refused stays where it is, because this is the only screen that could correct the
impression that it had come back.

**A bug caught by inspection, before it was written down.** Switching tabs does
not remount this page, so the first version of the restore handler cleared the
Movies list and left it to reload on its own — which it never would, because the
only thing that reloads it is a change of filter. The Movies tab would have gone
permanently, silently empty for anyone who brought a film back. There is a
reload trigger now, and a pin that switches tabs, restores a film, switches back,
and requires the list to have refetched — along with a negative control that
merely visiting the tab does not.

Ten pins across the two files, all mutation-verified.

## 2607.73.0 — Every request stopped asking the database who you are

Found while measuring the Missing page, and worth its own change because a
caching bug in the auth path is a security bug.

Every gated request read the account row **twice** — once to ask whether an
account exists, once to verify the token's signature. Two round trips on hosted
Postgres, on every poster, every page of an endless list, and every
twenty-second health poll, for a row that changes only when the owner changes it.

Measured on a configured instance:

| | before | after |
|---|---|---|
| `GET /api/missing/suggestions` | 5 statements (2 auth) | 3 statements (0 auth) |
| `GET /api/status` | 10 statements (3 auth) | 8 statements (1 auth) |

The remaining `settings` read on `/api/status` is the junk thresholds, not auth.

**Invalidation is the mechanism; the TTL is only a backstop.** Every writer drops
the cache, and a thirty-second expiry covers what no writer can see — a direct SQL
edit, a restore from backup, a second worker.

**`change_password` was already the dangerous one.** It merged the row directly
rather than going through `_store`, which nothing cared about before because there
was nothing to invalidate. With a cache in front of the read, that bypass would
have made a password change silently stop signing other sessions out — leaving a
suspected intruder signed in, which is the single thing that rotation exists to
prevent. It now goes through `_store`, and a source scan enumerates every writer
of the auth row and fails the build when one of them does not drop the cache. A
hand-maintained list would have been the other thing that got forgotten.

`clear_account` and the factory reset drop it too. The reset needs its own call:
it deletes the row by bulk `table.delete()`, which the ORM never sees.

The cache is keyed on the engine object, in a weak-keyed map. A URL string would
have worked — SQLAlchemy renders the password as `***`, so nothing secret lands
there — but it invites the question every time someone reads the code, two
engines differing only by password would collide, and the entries would
accumulate for the life of the process. The weak key answers all three.

**Two tests were closing a security gate by a route production never takes.**
They hand-merged `Setting(key="auth", value={"username": "x", ...})`, skipping
the password hash, the signing secret and now the invalidation — so they were
testing the fixture rather than the gate. Both now create a real account through
the real API, which is what caught the staleness in the first place.

Twelve pins. All seven mutations red — including one that had to be rewritten
because the original proved nothing: "hand out the cached dict itself" passed
either way until the pin stopped tampering with a copy taken on the *miss* path
and started tampering with one taken on a *hit*.

## 2607.72.0 — Three things the new Missing list got wrong

An audit of the surface shipped over the last few versions. All three were
introduced by that work rather than found lying around.

**A batch request with no ceiling.** `RequestAllButton` sends one request per
title in a sequential loop, and its bound used to be whatever the caller happened
to render — thirty behind a fold, or a collection's handful. The Missing list is
now endless, so after a minute of scrolling "request all shown" meant six hundred
films: fifty terabytes and an Overseerr queue to unpick by hand. The server's own
batch endpoint caps at fifty for exactly this reason, and this loop does not go
through it. The cap now lives in the component, not the caller, because no caller
should be able to hand it an unbounded set by accident — which is precisely what
happened. It is announced rather than applied silently: "Request the top 25 of
600", because a silent truncation is how someone finds out later that a hundred
films they thought they had asked for were never requested.

**An unbounded string into a fixed-width column.** `IgnoreIn.title` and
`.source` were written straight into `VARCHAR(512)` and `VARCHAR(32)`. Postgres
rejects an over-long value with an error that surfaces as a 500; SQLite ignores
the width entirely. So the bug passed every test and would only ever have
appeared on the owner's own database. Bounded at the schema, which turns it into
a 422 naming the field. `tmdb_id` is now `ge=1` as well — a zero or a negative
one is not a film, and a row nothing can match is a row nothing can explain.

**Three statements per scroll for numbers that do not change.** The page reads
sixty rows off an index; the total walks every one of the twenty-odd thousand
that match, through three correlated `EXISTS` clauses, and the requested/ignored
counts walk them again. Those three figures only move when the owner acts, so
they are now computed for the first page of a list and skipped for the pages that
continue it — measured on the real 25,000-row list, the count is 18 ms of the
page's 32 ms on SQLite, and on hosted Postgres each skipped statement is a whole
round trip. **The endpoint's own work goes from three statements to one.**

They come back as `null`, not `0`. "Not measured on this request" and "there are
none" are different statements, and a client that read the second would blank its
own header the moment anyone scrolled — "0 to go" on a list with twenty thousand
titles left reads as "you own everything", which is the exact lie this page was
fixed for two versions ago.

Fourteen pins, all mutation-verified.

**Found while measuring, not fixed here:** every gated API request costs one
`settings` read for auth — a round trip per request on hosted Postgres, on a row
that changes only when the account does. Left alone deliberately: a caching bug
in the auth path is a security bug, and it deserves its own change rather than a
ride on this one.

## 2607.71.0 — The list refills itself

The top-up shipped with a low-water check and nothing that used it. Its docstring
said "it only runs when the list is actually running low", which was true of a
caller passing `force=False` — and the only caller was the button, which forces.
The whole restraint mechanism was describing a code path nothing exercised.

It is now a scan phase, sitting between scoring and the AI pass and passing
`force=False`, so the service's own check does the deciding. On a library with
thousands of titles still queued that costs one count; below the water mark it
sweeps. Nobody has to notice the list was getting short and press a button, which
is the one thing nobody does — a list that is running out looks exactly like a
list that is nearly finished.

Guarded like the AI pass and for the same reason: a discovery sweep is a
convenience, and a dead TMDB or a rate limit must never be why a scan that read
the whole library reports failure. A skipped run is reported as skipped rather
than as zero added, because "added 0" and "did not look" are different answers
and only one of them means something is wrong.

`test_scan_phases_mirror` caught the frontend half before CI did — the checklist
in `scan.tsx` has to match `PHASES` exactly or the polling fallback divides by the
wrong number and the progress bar can never reach 100. That test exists because
`sonarr` once went in without it.

Five mutations, all red.

## 2607.70.0 — The corrections file actually corrects things

`list_overrides.json` shipped as the one place a judgement call belongs — the
generated lists are evidence-only, so a human decision needs somewhere to live
that a rebuild will not overwrite. It was only half wired: it filtered candidates
arriving from TMDB and the AI providers, and did nothing at all to the
twenty-five thousand titles already stored. Which is nearly the whole list, and
the half someone is looking at when they reach for the file. Strike a film out,
nothing happens, and there is nothing on screen to explain why.

Both directions now work, on the next scan:

* **`never_recommend`** keeps a title from being seeded *and* deletes the row if
  one is already there.
* **`always_recommend`** seeds the title into the canon at tier 1. The reason to
  write a title in here is that the generated list got it wrong, so the generated
  list does not get to outrank it.

A film named in both sections stays out — the same rule the exclusion list uses,
for the same reason: of the two readings, only one can lose a film for ever.

**Matching here is deliberately the opposite of `exclude_list.json`.** There, an
IMDb id decides alone, because that list is generated, id-keyed and complete over
its own domain — an id it does not mention is a film it has no opinion about, and
a title match would let a different film answer for it. This file is neither
generated nor complete: it is one person writing down a decision about a specific
film, using whatever they had to hand, and most people have a title and a year
rather than `tt0000009`. So a title-and-year strike lands whether or not the
stored row carries an id.

The prune is bounded by the size of the overrides file rather than by the canon —
ids matched in one `IN` clause, bare titles narrowed to their struck years in SQL
and paired up in Python, one delete over whatever matched. An empty file costs
zero statements, pinned exactly, because it runs on every scan.

**Two bugs the tests found rather than confirmed.** The seed-time filter and the
prune disagreed about hand-written strikes — one applied the exclusion list's
id-decides-alone rule and the other did not — which is how the divergence above
came to be written down instead of left implicit. And a first pass at the pins
put all six on the prune, which runs immediately after seeding and covered for
the seed-time filter completely: deleting that filter left every test green while
every scan would insert the struck title and delete it again, for ever. Those
pins now assert what `seed` *inserted*, not what survived it.

Sixteen pins. Nine of ten mutations go red; the tenth — deleting the early-exit
guard in the prune — is a genuine no-op, since an empty strike list reaches the
same `return 0` having issued no statements either way. The guard is there to say
so, not to do anything.

## 2607.69.0 — OpenAI, as an alternative rather than an addition

GPT can now do the work Claude does: the hard-reasoning pass, Ask, and the AI
half of the Missing list's top-up. Key it in Settings › Connections, or set a
bare `OPENAI_API_KEY` the way `ANTHROPIC_API_KEY` already worked.

**There is one hosted slot, not two.** Both providers answer the same question in
the same shape, so keeping both live would double the cost to get two opinions
nothing here is equipped to choose between — and nothing in Sift decides
correctness from an AI answer in the first place. Under tandem, Anthropic takes
the slot when it is keyed and OpenAI takes it otherwise. That order is deliberate:
an instance that has always used Claude keeps using it after an OpenAI key is
added, rather than silently switching which account gets billed.

Pinning the mode overrides the keys, and does so in both directions. `openai`
mode with only an Anthropic key configured resolves to **nothing** — not quietly
to Anthropic. A mode that can be overruled by a key is not a mode.

**The provider handles OpenAI's parameter rename rather than assuming it away.**
The output cap moved from `max_tokens` to `max_completion_tokens`; newer models
reject the old name and older ones predate the new one, and the model here is
typed in by hand. A request goes out with the new name and is retried once with
the old one — but only on that specific complaint. A blanket retry would double
every genuine failure, including a rate limit, which is the worst possible moment
to send a second request.

The Test button lists the models a key can actually reach, filtered to chat-capable
families: a key can see well over a hundred ids — embeddings, audio, moderation,
images — and a dropdown of those is worse than no dropdown. If the filter matches
nothing the full list is returned instead, because a key whose models are all
unfamiliar is still a valid key and "0 models available" reads as "your key is
broken". The model picker itself is no longer Anthropic-specific.

**A fix found on the way:** the health line said "Anthropic" whenever *anything*
was configured. That was already wrong for a local-only instance and would now be
wrong for an OpenAI one. Naming the wrong provider is worse than naming none — it
sends someone to check a key that was never in play. It now names what is actually
live, including both halves under tandem.

Thirty-four pins, every one mutation-verified.

## 2607.68.0 — The list stops running out

The Missing list read one file. Twenty-five thousand titles is a long way from
endless, and a library that works through it deserved a list that keeps going.
Two more sources now extend it, in the order asked for: TMDB discovery, then
whichever AI providers are connected.

**Everything lands in the same table.** A top-up writes a `canon_entries` row
exactly like the shipped list does, so there is one list, one ranking and one set
of subtractions — not a second surface to reconcile with the first. A separate
table would have needed its own paging, its own ignore handling, and its own
opinion about ordering: three chances to disagree with itself.

**Theatrical is asked of TMDB, not sorted out afterwards.** `with_release_type=3|2`
means theatrical or limited theatrical, which is the rule stated as a filter
rather than as a judgement — a film that opened in cinemas is a candidate however
badly it did, and a direct-to-video release is not. `with_runtime.gte=60` does
the same for shorts. Both cost nothing; filtering afterwards costs a page of
results per page of candidates.

**The exclusion list is now wired in** (`services/exclusions.py`), and matching is
deliberately asymmetric. Both files are keyed on IMDb id, which resolves exactly.
Where a candidate carries one, that id decides alone — an id absent from the list
means the list has nothing to say about *that film*, and falling through to a
title match would let a different film with the same name answer for it.
Title-and-year matching is only the fallback for candidates that arrive with no
id, which is what TMDB discovery and every AI provider hand back. Apostrophes are
deleted rather than turned into a space, because sources disagree about them
constantly and "Simba's Pride" and "Simbas Pride" are one film.

`list_overrides.json` outranks the generated list in both directions, and is the
only place a judgement call belongs. A film named in both sections is excluded:
of the two readings, that is the one that cannot lose a film for ever.

**AI is a source of candidates and nothing else.** Every title a provider names
still has to resolve on TMDB and clear the same deterministic gates — a
hallucinated film dies at the search. The must-have gating machinery is reused
through one new public seam (`musthave.gated_candidates`) rather than growing a
second prompt and a second parser, because one implementation of "an AI said it,
so verify it" is easier to keep honest than two that drift apart. The exclusion
list is applied *after* those shared gates, since an AI is the source most likely
to name a direct-to-video sequel and call it essential.

**It only runs when the list is actually running low**, or when someone presses
the button. Below five hundred actionable titles it is worth spending API budget;
above it, adding to a queue nobody has reached the bottom of buys nothing and
costs rate limit the canon resolution budget needs. A cursor in `settings` moves
each run further into each sweep — without it every run re-reads page one, finds
the same films, discards all of them as known, and produces nothing while burning
the same rate limit, which looks exactly like a feature that has run out of things
to find.

The Missing page's "Refresh catalog" button becomes "Find more", pointed at the
new endpoint. It reloads the list from the top rather than appending, because new
arrivals rank among the existing titles rather than after them.

Twenty-nine pins, every one mutation-verified. Two were vacuous on the first pass:
the "known films are never offered" pin was satisfied by a second guard at the
write, so it now asserts the count of what was *considered* — the gate exists to
stop a candidate reaching the AI stage, where each one costs a search and a detail
call; and the "reload from the top" pin was written with a single page loaded,
where reloading and paging ask for the same offset and the assertion holds
whatever the code does.

## 2607.67.0 — One Missing list, and a no that sticks

The Missing page had two lists behind two tabs, drawn from two different tables,
answering the same question twice. Neither of them remembered anything: a title
you had already requested came back, and a title you had explicitly passed on
came back too, at the same rank, on the next page load. That is not a queue you
can work through — it is a queue that resets.

There is now one list. It reads the 25,000-entry canon and subtracts three
things: what is in Plex, what you have already asked for, and what you have said
no to. The first two existed before in different places; the third is new.

**A refusal is stored against the film, not against the list row that suggested
it** (`ignored_titles`, keyed on `tmdb_id`). Keying it on the canon row would
have meant every list refresh resurrected everything already dismissed, because a
reseed writes new row ids for the same films. There is a pin for exactly that:
delete the canon, reseed it, and the answer has to hold.

"Remembered forever" applies to the suggestion engine, not to the owner. Nothing
ignored is ever proposed again by any source, but the ignored list is readable
and a single row can be taken back — a decision that cannot be reviewed is not a
decision, it is a black hole, and a mis-click on a 25,000-item list is a matter
of when rather than whether.

**Source count is not the ranking, and that is a measurement rather than a
choice.** 24,417 of the 25,000 entries carry exactly one source; tiers 3 and 4
carry one universally. Ranking by "how many lists vouch for this" would have been
a near-universal tie broken by whatever happened to come next. Tier already
encodes the same judgement with usable resolution, so the order stays
`(tier, -votes, tmdb_id)`. Multi-source counting becomes meaningful once the AI
sources are attached and can actually disagree with each other.

A page costs two statements at any page size, pinned exactly rather than
loosely — all three subtractions are `EXISTS` clauses inside those two, and
pulling any one of them into Python costs precisely one more round trip, which a
bound of "a handful" would have let through.

**On screen, three surfaces became one.** Missing had a Movies tab and a Canon
tab drawing from two different tables, and Taste Profile carried a third
recommendation shelf underneath the weights. None of them agreed with each other
and none of them remembered anything. The Canon tab and the Taste Profile shelf
are gone, along with the components and client methods behind them; the Taste
Profile weights still reorder what is left.

The list itself now scrolls rather than ending at thirty with a "show all"
button — sixty at a time behind a sentinel, with the same dropped-page handling
the Library uses: a failed page rolls the offset back so a retry asks for the
titles that were lost rather than the ones after them, says the list is
incomplete rather than borrowing "that's everything", and stops asking until the
retry is clicked. That last guard was untested until a mutation showed it: in
jsdom the observer only fires when a test tells it to, so an unbounded retry
loop against a struggling server was invisible. There is a pin for it now.

Acting on a card leaves it in place, dimmed, instead of removing it. On an
endless list a card that vanishes under the cursor hands its position to the next
one, and the click already on its way lands on a film nobody decided about.

## 2607.66.0 — A 25,000-film canon, and an exclusion list built from evidence

Two lists, both derived from public data, neither hand-authored.

**The canon goes from 10,000 to 25,000.** Every original entry is carried over
untouched — those came from Criterion, the cult canon, award records and the film
registry, and no ranking of votes improves on them. The 15,000 new entries are
IMDb features with at least 1,000 votes, ranked by weighted rating and tiered 2–4
by fill rank, so they sit below the curated pillars rather than displacing them.

The vote floor is a floor on **reach**, not quality. A poorly received theatrical
release is in the list; it just ranks last. People watch bad films on purpose, and
a recommender that silently deletes them is deciding something it was not asked to
decide.

**The exclusion list is 23,937 direct-to-video and made-for-TV releases** — the
B-picture and C-picture end of the catalogue. Membership is a fact about how the
film was released, recorded by IMDb at publication, not a judgement anyone made
about whether it is any good. That distinction is the entire design: a
hand-written list of "bad films" would have been one person's opinion wearing a
data costume, and the one file in this repo that nothing could check.

Two refinements came out of looking at what the first build actually caught,
rather than from reasoning about it:

- A **60-minute floor** on the canon. IMDb files hour-long documentaries and TV
  specials as `movie`; the first build put a 57-minute documentary in the canon.
- An **escape hatch** on the exclusions: rated 7.0+ with 25,000+ votes and it stays
  recommendable. Without it the rule deleted 52 films people genuinely want —
  Spielberg's *Duel*, *The Animatrix*, the DC animated features, the 1966 *Grinch*.

`list_overrides.json` is the one place a judgement call belongs. The generator
never writes it, so hand corrections survive a rebuild by construction.

The size assertion in `test_canon_entries.py` caught the swap, which is what it is
for — the shipped row count is a fact about the data, not a detail to update
quietly.

Documented in `docs/RECOMMEND_LIST.md` and `docs/EXCLUDE_LIST.md`. Rebuilt by
`tools/canon/build_lists_from_imdb.py`, which needs only the standard library and
two public downloads. Nothing is wired to the exclusion list yet.

## 2607.65.1 — Test the banner I shipped without one

Tests only; no behaviour change.

The "these credentials can no longer be read" banner went out with backend tests
proving the server reports the right thing, and **nothing at all** covering the
part an owner actually looks at. The server could have been perfectly correct
while the banner never rendered, and the first person to find out would have been
someone staring at an empty field again.

Two tests, both mutation-verified: hiding the banner turns one red, showing it
unconditionally turns the other red. They click through to the Connections tab
first, because that is not the tab the page opens on and a test that skipped the
click would be testing a screen nobody arrives at.

## 2607.65.0 — Thirty thumbnails, one connection pool

The last of the poster-page costs, and the smallest — but on the same page and
the same load.

An `httpx.AsyncClient` owns a connection pool, and one was being built per
download. Thirty thumbnails meant **thirty pools and thirty TLS handshakes** to
the image host, none of them reused. The cache now keeps one client, created
lazily so an instance that never fetches a poster never opens a socket, and
closed when the app shuts down or a settings change swaps the cache out.

That last part is why the change is not purely additive: a pooled client that is
never closed leaks its connections on every settings save. The negative control
covers the obvious overcorrection — closing it must not make the cache a one-shot,
or the next scan finds a dead client.

Two tests, both mutation-verified.

## 2607.64.0 — The three read paths that still blocked, and a guard for the rest

The previous release fixed the acute case and listed twelve others in a document.
A list in a document is not a guard, so this fixes the three on pages you open and
replaces the list with a test.

Off the event loop now: the **Settings page** load, the **TV suggestions** on
Missing, and the **recommendations** shelf. Each was one round trip rather than
thirty, which is why none was urgent — but Settings is the page you are sent to
when credentials need re-entering, and blocking the process while that page loads
is a poor place to do it.

The remaining nine are named in a test rather than prose. It reads the route
modules, finds every `async` handler that opens a database session, and compares
that set against an explicit list. **A new one fails it. Fixing one without
removing its name also fails it** — a list that is allowed to drift stops
describing anything.

Structural rather than timed: it catches the next handler somebody writes, and it
does not depend on how fast the machine is.

The negative control is the one that earns its keep. A scanner that finds nothing
passes the pin above perfectly, so it is fed the exact shape it exists to catch,
a plain `def` it must ignore (FastAPI runs those in a threadpool), and a handler
already using `in_thread`.

## 2607.63.0 — Thirty thumbnails stopped blocking the whole server

A better answer to "the Missing page times out" than the last one.

Every poster has to read the database to find out where its artwork lives. That
read ran **on the event loop**. Against the SQLite these tests use it costs
microseconds and is invisible; against a hosted database it is a network round
trip, and while one is in flight nothing else in the process moves — including the
page's own API call.

The Missing page asks for thirty thumbnails at once. Measured, with a 50 ms
database read: **1.57 s serialised, under 0.5 s overlapped.** And "serialised"
here does not mean the posters merely wait for each other — it means the server
is unavailable for the duration.

The database reads and the file writes now run on worker threads, through the
`in_thread` helper the pipeline and AI modules already use for exactly this.

Two tests. The pin counts how many reads are **in flight at once**, not how long
they take: a wall-clock threshold would depend on how many worker threads the
machine gives us and how loaded it is, which is exactly how a test passes locally
and fails in CI. On the event loop the count can only ever be one. The control
checks the bytes still arrive, because a cache that stopped serving posters
altogether would be perfectly concurrent.

**Still outstanding, and worth naming rather than leaving to be rediscovered:**
twelve other `async` endpoints do synchronous database work on the loop the same
way. They matter far less — each is one request rather than thirty at once — but
the pattern is the same and the fix is the same. Listed in
`docs/ENGINEERING.md`.

## 2607.62.0 — Two reported bugs: keys that "won't save", and Missing hanging

### Your keys were saved. Then the key that opens them changed.

Service credentials are encrypted before they go in the database, under
`SIFT_SECRET_KEY` — or, where no separate secret key is set, under
`SIFT_SERVER__API_TOKEN` as a fallback. Rotate either one and everything saved
beforehand becomes ciphertext nobody can open.

The app said nothing. An unopenable secret decrypts to `None`, every consumer
reads that as "not configured", and the field shows empty — **identical to never
having entered it**. That is what "my keys aren't being saved" looks like from the
inside, and it is a fair reading of what the screen was showing.

Reproduced against a running server: save a Radarr key, restart with a rotated
token, and `api_key_set` flips from `true` to `false` with nothing explaining
why. (Re-entering it does work, and does stick.)

Settings now names them: how many, which services, which fields, and why —
rotating the key makes anything saved before it unreadable, the values cannot be
recovered, enter them once more and they stay. The banner clears when you do.

**If this is you, the fix is one pass through Settings.** Check whether
`SIFT_SECRET_KEY` is set in Render first — if it is not, the access token is
doing that job, and rotating the token will do this again.

### The Missing page had a poster problem, and no way to give up

Every title on that page is one you do *not* own, so none of them has a `movies`
row — and poster resolution only ever looked there. Each thumbnail fell through to
a live TMDB lookup: one network round trip per poster, on a page that shows thirty
at once. Worse, the resolved URL could not be cached back, because there is no row
to write it to, so it repeated whenever the image cache went cold — every redeploy
on an ephemeral disk.

The path was in the database the whole time. The canon refresh stores
`canon_movies.poster_path` for exactly these titles and nothing read it. It is
read now, and a film you own still wins with its own artwork.

Separately, no page-level read had a time limit, so a request that never came back
left the screen loading for ever — indistinguishable from slow. Every read a user
watches a spinner on is now bounded at 45 seconds and lands in the error-with-retry
state those pages gained earlier today. Generous on purpose: a sleeping free-tier
instance takes about thirty seconds to wake, and giving up on that would turn a
slow first load into a failure.

Nine tests, all mutation-verified.

## 2607.61.0 — The asset token now dies with the session it belongs to

Changing your password rotates the server's signing secret. Every token issued
before it stops verifying — the asset token included.

Nothing told the browser. The minted asset token sat in memory with a clock
saying it was good for another forty minutes, and went on being sent: **every
poster 401ing and a scan socket that would not open**, for the rest of its
nominal life, immediately after a password change.

Storing a new session token now forgets the asset token, and a password change
mints a replacement straight away rather than leaving the next poster to discover
the old one is dead.

Two tests, mutation-verified. The control matters here: throwing the token away on
every read would satisfy "it is not reused after a password change" perfectly and
re-mint constantly, which is a different waste — so an unchanged session has to
keep the token it was given.

## 2607.60.0 — The session token stopped travelling in poster URLs

Asset tokens exist because an `<img>`, a download link and a WebSocket cannot
send a header, so their credential rides in the query string — and query strings
are recorded by every proxy they pass and kept in browser history. The short-lived
asset token is what should travel there; the thirty-day session token opens the
entire API.

The gate that mints the asset token kicked the request off **without waiting** and
rendered immediately. So the first screenful of posters — sixty of them on the
library page — went out carrying the session token, on every single load and every
sign-in. The fallback that made that happen is commented as a last resort; it was
in fact the ordinary path.

The gate now waits for the mint. The fallback stays, because a page of broken
thumbnails is a worse failure than a stale credential in a URL, but reaching it
now means the mint actually failed.

**Waiting introduces its own risk**, so the mint carries a four-second timeout: a
request that hangs must give up and let the app render rather than holding the
whole UI behind it. That is what the negative control checks — and it replaced a
first draft that was vacuous. "A *failed* mint still renders" cannot fail: the
gate already catches rejections, so no plausible mutation breaks it. A *hang* is
the one that can genuinely strand someone, and removing the timeout turns that
test red.

Six tests, mutation-verified — including two on the server side that this change
makes load-bearing. The browser now always sends the asset token to the three
routes that carry a credential in a URL, so every one of them has to accept that
scope; the scan socket was covered for session tokens and bad tokens but not for
the one the browser will actually send. A route that quietly required a session
token would pass the tests, which call it directly, and fail in the browser, which
no longer has one to give it.

## 2607.59.0 — First run on a hosted deploy was impossible

A bug I introduced, found by reading my own deployment docs.

The security work made first-run account creation require the deploy's access
token — correctly, because a hosted instance is reachable by anyone who finds the
URL, and without it whoever arrives first gets the account. But the wizard sent
only a username and a password. It got a **401**, had nowhere to put a token, and
no way to learn one was wanted: `/api/auth/status` reported `setup_complete:
false` and nothing else.

On Render, where the Blueprint generates `SIFT_SERVER__API_TOKEN` for you, that
means **the app could not be set up at all**. Anyone deploying fresh — or
re-deploying after the free tier wiped the ephemeral database, which the deploy
guide warns happens — hit a login screen that refused them.

`/api/auth/status` now reports `setup_requires_token`, and the wizard asks for it
where it is needed, naming where to find it. Where no static token is configured
— an ordinary local install — nothing changes and no field appears, because a
field nobody can fill in is worse than no field.

One related fix: an explicitly supplied credential now wins over the ambient
session token in the API client. A stale token in browser storage would otherwise
have been sent in place of the deploy token, which is the same 401 by a different
route.

Six tests, all mutation-verified, across both halves. Verified end to end as
well, against a running server with a token configured: the flow that returned
401 now returns 201, and the flag turns itself off once an account exists.

**The docs that found it are corrected too.** Step 6 of the deploy guide still
described an "unlock screen" where you paste a token — the flow from before there
were accounts at all. And the Neon route said nothing about the **transfer
allowance**, which is the limit that actually takes an instance down: the free
tier meters bytes moved, so scan frequency is what exhausts it, and a two-hourly
scan moves twelve times what a daily one does. Both now say so.

## 2607.58.0 — Guard the whole scan's cost, and write down the trap in reading it

No behaviour change. A test, and a piece of knowledge that had cost three
sessions to rediscover.

The per-phase pins guard the phases that were once wrong. Nothing guarded the
shape of a whole scan — which is where the failure that started this actually
lived: a `session.merge()` per film, four statements each, invisible on local
SQLite and minutes of pure latency against a hosted database.

**The trap.** On SQLite, SQLAlchemy batches ORM inserts into one statement only
when we supply the primary key; a table with an autoincrement id gets one INSERT
per row, because the ids have to come back. So `movies` and `plex_copies` (keyed
on tmdb id and rating key) insert in a single statement while `ratings` and
`seasons` (autoincrement) insert one at a time — and on Postgres, where this
actually runs, both batch.

A raw statement count therefore reads as "one per film" against a scan doing
nothing of the kind. I measured 120 inserts into `ratings` for 120 films, went
looking for the per-row write, and found the dialect instead. The obvious "fix"
would have been a rewrite that buys nothing on the database this ships to. It is
written down in the test now so it does not have to be found a fourth time.

What the test counts instead is what a per-row round trip shows up as in either
dialect: a SELECT or an UPDATE per film. Measured as a *slope* — two libraries of
different sizes, compared — because reads legitimately grow a little with the
number of Plex batches, so any flat threshold is either too loose to prove
anything or breaks when the page size changes.

**Two mutations I nearly recorded as passing.** The first attempts targeted the
Radarr phase, which runs *after* Plex — so by then every film already exists, the
`is None` branch never runs, and both mutations were no-ops the tests could not
have caught. Aimed at the Plex phase, where the films are actually created, both
turn the pins red. A mutation that changes nothing proves nothing, and it looks
exactly like a mutation that was caught.

## 2607.57.0 — Counting the junk queue stopped fetching the films in it

The header badge is a number. It was produced by building the list.

`/api/status` is polled for as long as a tab is open, and its flagged-titles
figure came from `len(candidates(..., limit=10_000))` — so counting them
hydrated every candidate, poster URL and overview included, to take the length of
the result. The previous release halved that read; this removes it. The ranking
pass already knows the ids, so the count now stops there and no film is fetched
at all.

Two tests. The control that matters is not the one comparing the count to the
list — both now walk the same selection pass, so a change to the rule moves them
together and they still agree. It is the `protect`-verdict pin: mutate the shared
rule and *that* goes red, which is the only reason the divergence would be
caught. Worth stating plainly, because "the count agrees with the list" reads
like a stronger guarantee than it is.

## 2607.56.0 — Collections stopped reading every set to show the incomplete ones

The same shape as the Junk page, one screen over.

Which collections qualify is decided by two counts already stored on the
collection row: you own some of it, and not all of it. Showing one needs its
members. The order was backwards — every member of every collection was read and
hydrated as an ORM entity and sorted, and only then was the question asked. Most
of that belongs to collections that are already complete (nothing to show) or
wholly unowned (not yours to complete), and it crossed the wire on every load of
the page.

The counts are filtered in SQL now, and members are read only for the collections
that survive.

Measured on 200 collections of 20 members each, 20 of them incomplete: **4,200
rows to 420, and 117 KB to 9.8 KB.** The ratio is not a constant — it is the
fraction of your collections that are actually interesting, so a library where
most sets are half-finished saves less, and one where most are complete saves
more.

Four tests, all mutation-verified. Two of them guard the boundary rather than the
cost: `owned_count == 0 or owned_count >= total_count` became two SQL
comparisons, and either is easy to get wrong by one — a `>=` where a `>` belongs
puts complete sets back on the page. Both off-by-ones were tried, and both go
red.

The fourth is the one worth having: scoping a member read by collection id can
drop a collection's members silently, which shows the gap with an empty member
list — indistinguishable, on screen, from a set you have already completed.

## 2607.55.0 — The Junk page stopped reading the whole library to show two hundred rows

Deciding whether a title is a removal candidate needs two things: its score and
the classifier's verdict. *Rendering* one needs the film itself. The query asked
for both at once, so every non-kids title in the library arrived fully
hydrated — all thirty-one columns of `movies`, `overview` and `poster_url`
included, plus the `signals` JSON — in order to show a couple of hundred and
discard the rest. There was no `LIMIT`: the slice happened in Python, after
everything had crossed the wire.

This is asked on every visit to the screen.

It reads in two passes now. The first selects no `movies` columns at all beyond
the id it joins on, and stops as soon as it has enough candidates. The second
fetches those winners whole.

Measured on a 2,000-film library with 300 candidates, showing 200:
**2.06 MB down to 659 KB, a 3.1× cut.** (Measured as the size of the values
returned, on SQLite — a proxy for wire bytes, not an exact count of them.)

The verdict still has to be filtered in Python. It lives inside the `signals`
JSON, and a JSON predicate compiles differently on SQLite, where the tests run,
and Postgres, where this actually runs — which is precisely the blind spot that
hides this class of bug in the first place. So `signals` is still read for the
whole library; the wider `movies` half is not.

Three tests. One of them was **vacuous when first written** and caught by its own
mutation: the fixture seeded scores in the same order as the ids, so an `IN`
query returning its own order looked correctly ranked. Seeding the two in
disagreement makes the ranking assertion mean something, and the mutation now
fails as it should.

The other two controls: the same films must come back in the same order as the
slow whole-library computation, and a `protect` verdict must still keep a
high-scoring title out of the queue — the one part of the decision that could not
move into SQL, and the one whose loss would put cult classics in the removal
queue.

## 2607.54.0 — Check that the browser and the server agree on their routes

The one seam neither suite covered.

Frontend tests mock `api` wholesale — that is what makes them fast and what makes
them blind to the strings inside it — and backend tests never see the client at
all. So a renamed or removed route was a 404 that appeared only in a real
browser, on whichever screen nobody happened to open before shipping.

A structural test now pulls every path out of `api.ts`, pulls every route off the
app, and requires the first to be a subset of the second. All sixty-five client
paths resolve against seventy-five routes today.

Mutation-verified from **both** sides, because a rename can start on either:
pointing the client at a route the server does not serve turns it red, and
renaming the route on the server turns it red too.

Two negative controls, and they earn their place here more than usual. A subset
assertion passes trivially when one side is empty, so the test refuses to run
against fewer than fifty paths on either side — a broken matcher now fails loudly
instead of silently agreeing. And the normaliser has its own control: stripping a
trailing `${...}` is right for an interpolated query string and wrong for a path
parameter, and getting that backwards flattens `/api/config/test/{}` into
`/api/config/test`, which either reads as a false alarm or, worse, matches
something else and hides a real one.

## 2607.53.1 — Make the README describe the app that exists

Documentation only; no code changed.

The README still opened with **"Phase 0 — Skeleton + read-only ingestion (in
progress)"** and listed four API clients and four endpoints. The app has ten
screens, six clients, TV ingest, a reclaim ledger and a storage planner. A stale
README is not a cosmetic problem — it is the first thing anyone reads, including
a future session picking the work up cold, and it was describing a different
program.

Corrected: what is actually in the app, the architecture diagram (Sonarr and the
agent-claimed file jobs were missing entirely), the source-of-truth table, the
project layout, and the fact that it runs on Postgres when `DATABASE_URL` is set.
The test section now lists all five gates CI runs rather than `pytest` alone, and
says what a negative control is and that controls are mutation-verified — the
house rule was written down nowhere a newcomer would look.

Removed the "Phase 4" promises that no longer describe anything.

## 2607.53.0 — The last two screens that swallowed a failure

Same defect, same sweep, the two remaining pages that had it.

**Collections reported a complete shelf.** A failed read emptied the list, and an
empty list on that page means "every set you own part of is complete" — the
opposite of what had happened.

**The taste profile span for ever.** A failed read left `data` null, and null is
the loading state, so the skeletons stayed up permanently. A spinner that never
resolves is the least informative failure a screen can have, and it is the shape
of "the app is completely broken" from the browser.

Both now name the failure and offer a retry that refetches. The loading branch
also gained the `aria-busy` / `role="status"` pair the other pages already had,
so a screen reader is told it is waiting rather than left in silence.

Six tests, each mutation-verified, two of them negative controls: a genuinely
complete shelf must still read as good news, and a library with nothing in it yet
must still say to run a scan.

That is every page in the app checked for this. The remaining `.catch` handlers
are on writes, where a toast already reports the failure and the screen is not
claiming anything about your library.

## 2607.52.0 — Two screens that lied when the database stopped answering

Both of these are the screen you were looking at when the app read as completely
broken, and both were saying something reassuring at the worst possible moment.

**Missing emptied its list on failure.** A failed read set the list to `[]`, which
renders as "nothing is missing from your library" — untrue, the most flattering
possible lie, and indistinguishable from a database that had stopped answering.
It now names the failure and offers a retry that actually refetches, the way the
Junk queue already did.

**The Dashboard advised a scan.** A failed status read fell through to "No
snapshot yet — run a scan to build one": advice that cannot possibly work,
offered at the exact moment nothing could. It now shows what actually happened.
Since the server learned to say *"the database is not accepting queries"* rather
than "Internal Server Error", that sentence now reaches the screen instead of
being swallowed one layer short of it.

Five tests, each mutation-verified, and two of them negative controls — a
genuinely empty catalog must still offer to build one, and a genuinely empty
library must still say to run a scan. Without those, "show an error" and "always
show an error" are the same test.

`PrefsProvider` joined the test harness: the Dashboard is the first tested page
that needs it, and a harness missing a provider the real app has is a harness
that tests something the app never runs.

## 2607.51.0 — Pin the two screens that can delete a file

Both destructive paths were covered on the server and uncovered in the browser.
The engine refuses an unapproved delete, and every test of that lives in Python —
so a screen that proposed first and asked afterwards would have been caught by
nothing, and the confirmation dialog would have been decoration.

Six tests across Junk and Storage, each mutation-verified:

* Neither screen contacts the server until the dialog is answered, and cancelling
  contacts it not at all.
* The Junk row button removes **the row you clicked**, not everything ticked.
  Titles arrive ticked by default — deliberately — which is exactly what makes a
  per-row button dangerous if it reads the selection instead of its own row. That
  mutation was tried and the test caught it.
* The approval is its own explicit call rather than something `propose` is
  trusted to imply. Deleting the `approveAction` line turns the test red.
* Storage sends exactly the paths it showed in the dialog, and reports a
  *proposal* — "approve it on Activity" — rather than implying the space is back.

No behaviour changed. This is the browser half of a guarantee that was only ever
enforced on the server.

## 2607.50.0 — A short recommendation list says why it is short

"Why am I only getting five?" was answerable from the database and not from the
screen, which is the actual defect. The list reports its composition now, but a
canon half that reads *"2 from the validated canon"* still leaves the obvious
question hanging.

There is one cause far more often than any other. The canon arrives keyed by IMDb
id and the library is keyed by TMDB id, so only entries that have been resolved
can be compared — an unresolved remainder is not a missing feature, it is a list
that has not finished filling in. Where the queue comes back shorter than asked
for, the note now names that remainder: *"37 canon titles have no TMDB id yet —
they join the list as resolution catches up."*

It appears **only** when the list is actually short. Printed unconditionally it
becomes furniture: read once, ignored afterwards, and silent on the one occasion
it matters. That is the negative control, and it is mutation-verified alongside
the pin itself.

The coverage query costs four counts and is asked only on the short path.

## 2607.49.0 — Page the canon in the database, not in Python

Asking for a page of unowned canon read the whole canon.

The query had no `LIMIT`: every matching entry was loaded and the page was then
sliced out of the list in memory. Ten thousand rows across the wire to draw a
screen of two hundred — and since recommendations became canon-first, that read
now happened on every scan as well as every page view, which made it the largest
read the recommendation shelf performs.

Paging moved into SQL. The remainder is counted with a separate `COUNT` rather
than measured by reading it, because what the caller needs from the rest is how
big it is, not what is in it. The reported total is unchanged, and so is the
order.

Two tests, both mutation-verified. The paging control matters more than the size
one: an off-by-one in the offset is invisible within a single page and loses a
film between every pair of them, so it walks three consecutive pages and requires
them to reconstruct the unpaged list exactly.

## 2607.48.0 — Say what the recommendations are made of

The recommendation shelf still described itself as the taste graph, and still
printed one fixed sentence about being "grounded in your highest-rated titles via
TMDB". Since the list became canon-first that is simply untrue, and it was
untrue in the one place the description mattered: a list that comes back short
looks broken unless it says what it is made of.

The server has reported its composition since the canon change — *"180 from the
validated canon, 20 from your taste graph"* — and nothing showed it unless the
list was empty. It is now printed under the shelf whenever there is a list, and
the badge reads "Canon + taste" rather than naming only the half that can fail.

**The taste profile read the whole library to count three things about it.**
Genres, keywords and decade — while `select(Movie)` ships all thirty-one columns
per film, `overview` and `poster_url` included, and those two are larger than
everything the page uses. The credits join had the same shape: a job and a name
taken off two fully hydrated rows, a dozen times per film. Both are column reads
now. This runs on every view of the profile page, so it was a whole-library read
per page view.

Three tests, mutation-verified, one of them the negative control that a profile
reading nothing at all would otherwise pass.

## 2607.47.0 — Write a season once, not twice

A first TV scan wrote every season to the database twice.

The id was needed to hang episodes off, so each new season was flushed the moment
it was created — before any of its statistics had been assigned. The insert
therefore stored an empty row and the next flush issued an UPDATE to fill it in.
A library of long-running shows creates thousands of seasons, and each one cost
two writes rather than one. The per-season flush also stopped the shows in a
batch from being inserted together, so those went one statement at a time too.

Episodes are now queued while their seasons are still id-less and written after a
single flush for the whole slice, which means the attributes are set before the
insert and there is nothing left to update.

Measured on a 20-show, 5-seasons-each fixture: **574 statements to 395**. The
100 redundant `UPDATE seasons` are gone entirely and the show inserts collapse
from 30 statements to one. Nothing about what is stored changed.

Two tests, both mutation-verified. The negative control is the one that matters:
a season inserted empty and never updated would satisfy a "no second write" pin
perfectly while losing every figure the storage page is built on, so the control
reads the rows back and requires the sizes, counts and air years to be there.

## 2607.46.0 — Stop paying per file for work that is one request

Three reads that grew with the library while the request stayed the same size.
None of them was slow enough to notice locally, because local means SQLite on the
same machine; all three are round trips or bytes across the wire against a hosted
database, which is what the app actually runs on.

**The poster cache statted the whole cache directory on every fetch.** The
question it was answering — "am I over the 500 MB cap?" — is almost always no,
and it was being answered by summing the size of every file on disk. A library
with fifteen thousand cached posters paid fifteen thousand syscalls per newly
fetched thumbnail, and the first scroll through a library fetches hundreds. The
total is now carried in memory: measured once per process, incremented per write,
and re-measured only when an eviction has actually changed it. The pin is the
shape rather than a number — forty times the cache, the same handful of syscalls.

**The storage page read its widest join twice.** Season sizes and season
inconsistencies are two questions about one set of rows: every episode file
joined to its season and its show. Each was loading that join for itself, so
opening the page shipped a TV library's entire file metadata across the wire
twice. The reclaim ledger already loaded it once and passed it to both; the page
now does the same.

**Approving a set of deletions committed once per file.** Each staged job was
committed and then read back to pick up its id — two extra round trips per file,
so approving a show's worth of duplicate episodes cost scores of them for a
single button press. It is now one flush and one commit. Every file still gets
its own job row, its own size, and its own individual approval: this changes how
the rows are written, not what is written or what has to be agreed to.

The commit and the read-back are what the new test counts, not the inserts — the
inserts collapse into one statement on Postgres and stay one per row on SQLite,
so counting them would pin the test database's behaviour rather than the app's.

Also removed `useMovies`, a hook with no callers.

Six new tests, each mutation-verified by breaking the implementation and
confirming the test goes red. Three of them are negative controls: the poster
counter must be re-measured after an eviction or it evicts forever; the shared
join must give the same answers as two separate loads; and every approved file
must still get its own job row, because a cheaper write that quietly dropped
eleven of twelve deletions would satisfy the count and defeat the per-item gate.

## 2607.45.0 — Recommendations start from the canon

Three to five results instead of two hundred, varying between visits. The count
was the symptom; the cause is that the list had one supply line and it was a
fragile one.

Every recommendation came from the taste graph, which needs **all** of: owned
films that already carry TMDB ratings (to seed anchors from), sixty live API
calls to succeed, and the results not to be films you already own. Thin anchors,
a rate-limited or flaky TMDB, or a well-stocked library that already contains
most of what gets suggested — any one of those collapses the list, and none of
them said anything on screen. Worse, each failure was caught per anchor and
skipped, so partial collapse looked exactly like a short answer.

**The canon runs first now.** Ten thousand vetted titles, already resolved to
TMDB ids, sitting in the database — no API call, no dependence on ratings, no
dependence on anything being reachable. Unowned canon entries fill the list in
tier order: the strongest claims first. The taste graph then *extends* that with
titles the canon does not mention, and nothing appears twice.

That is the shape the owner asked for — work through the list we already have,
then reason about what else belongs — and it is also the robust one. The half
that can fail is now the half that only ever adds.

**The composition is reported rather than left to be guessed at.** The response
says how many came from each source, and the scan records both figures in its
counts. A short list can now be read: few from the canon means resolution has
not caught up; few from the graph means anchors or TMDB.

Three new tests, each mutation-verified: removing the canon half, letting owned
canon titles through, and allowing a title supplied by both halves to be stored
twice each turn a pin red. The negative control is the one that matters — filling
from the canon must never mean recommending films already on the shelf, which
would be worse than a short list.

## 2607.44.0 — Clear the dependency advisories

`npm audit` reported **zero** after this, against one high and one moderate
before. Two bumps, deliberately separated from the testing work that surfaced
them, because bumping a router inside an unrelated change is how routing breaks
quietly.

**`react-router-dom` 7.18.1 → 7.18.2.** A patch inside the same major, which is
what the advisory needed. Worth stating plainly: the flaw is a CSRF bypass in
React Router's **RSC mode**, and Sift is a plain single-page app that does not
use RSC — so the real exposure here was nil. It is fixed because a known
advisory sitting in a runtime dependency is a thing you have to re-reason about
every time you look at it, not because anything was reachable.

**`vite` 5 → 8, with `@vitejs/plugin-react` 4 → 6.** This one is genuinely
dev-only: the advisory is path traversal in the *dev server's* handling of
optimized-deps source maps, and production is FastAPI serving a built `dist`
directory, which never runs Vite at all.

The major bump needed one real change. Vite now bundles Rolldown, which takes
`manualChunks` **only as a callback** — the object form does not degrade, it
fails the build. The vendor chunk is now selected by matching module paths, and
comes out the same size it was. Two happy side effects: the deprecation warnings
Vitest was printing on every run are gone, now that both sit on the same
bundler, and the moderate `esbuild` advisory went with it.

Verified past the version numbers: sixteen frontend tests and the full backend
suite still pass, the bundle still builds, and `dist` still ships **no source
maps** — which is the thing the earlier security pass turned off, and exactly
the kind of setting a major build-tool upgrade quietly resets.

## 2607.43.0 — The frontend gets a test harness

Until now the frontend had **no tests at all**. `tsc --noEmit` and a successful
bundle were the only gates, which check that the code compiles and say nothing
about whether it does the right thing. The last several releases fixed component
logic of exactly the kind that regresses silently — a catch that emptied a list,
a selection rebuilt from a response, focus landing on the destructive button —
and none of it was pinned by anything.

Vitest with Testing Library over jsdom, run by `npm test` and **gated in CI**, so
it fails a pull request rather than sitting there decoratively.

**Sixteen tests, covering the bugs the recent releases fixed:**

* a failed junk fetch says so instead of reporting "All caught up"
* retry actually refetches
* staged and live are each stated before anything is clicked
* a title can be kept from the keyboard
* the confirm dialog focuses Cancel, so Enter on open cancels rather than deletes
* focus is trapped in the dialog and returns to whatever opened it
* a dropped library page says the list is incomplete, and retries **the page that
  failed** rather than the one after it
* the activity log distinguishes "could not load" from "nothing has happened"

Every one has a negative control, and **every control is mutation-verified**:
reverting each fix in turn turns the matching test red, and each was checked
individually rather than assumed. Two of the tests were rewritten first — one
stubbed the intersection observer into silence, so paging never happened and the
test proved nothing; the other used a short first page, which tells the list it
has reached the end for the same reason.

Scope is deliberately narrow. These check logic, not appearance. Markup snapshots
fail on every deliberate change and pass on every change that matters, which
trains people to update them without reading them — so there are none, and how it
*looks* stays a human judgement.

One thing found on the way in: the versions first installed carried two critical
advisories in the test runner itself, so it ships on current ones instead.
`react-router` and `vite` carry high advisories that predate this and are
untouched here — worth their own change rather than a silent bump inside a
testing PR.

## 2607.42.0 — A finished scan now changes the screen

**Scanning updated nothing you were looking at.** From the Junk page you could
press "Run scan" in the header, watch the panel count to 100%, watch it close
itself — and the queue underneath was still the pre-scan list, with no hint that
it had gone stale. The only way to see the new state was a manual reload. The
completion hook existed in the scan provider and was simply never passed.

Junk and Storage now refetch when a scan finishes. **Refetch, not reload**: a
full page reload would throw away scroll position and anything half-armed, which
on a screen full of delete buttons is its own small betrayal.

**"Approve all" ignored the selection sitting beside it.** Two bulk paths were on
screen at once: a sticky toolbar reading "Approve removal (12)", which acted on
what you had ticked, and a header button reading "Approve all (200)", which acted
on every undecided row regardless. Spend five minutes curating a selection and
the second button silently discards it — and the broader, more destructive one
was styled as the quieter of the two.

It now reads "Select all and approve", and ticks the rows first, so the count on
the button, the count in the toolbar and the list in the confirm dialog all agree
before you commit to anything.

## 2607.41.0 — Work the queue from the keyboard

**Reviewing a queue was mouse-only.** Sift has a real shortcut system — `g` plus a
letter to navigate, `/` to search, `?` for help — and it stopped at the door of
the thing you actually do most. Deciding two hundred junk candidates meant two
hundred rounds of move, click, dialog, click.

Rows are now focusable, and on a focused row: **`k`** keeps it, **`x`** toggles
its selection, **Enter** opens the details. All three are listed in the help
overlay. Typing in a field is excluded, so the search box keeps its letters.

**The select checkbox was a 16-pixel target sitting next to a delete button.**
It now carries a 44-pixel hit area while looking exactly the same — a negative
margin around an oversized label, so nothing moves and the pinprick goes away.

**The drawer no longer re-renders the whole library to open one panel.** Its
context held both the actions and the currently-open film in one value, so every
open and close produced a new context object — and `memo` does not stop a context
update. Every mounted tile re-rendered, twice per interaction. Library appends on
infinite scroll and never trims, so after scrolling a large library that is
thousands of re-renders for a click that changes one panel.

It is two contexts now: a stable actions object that never changes identity, and
the open film, which only the drawer itself subscribes to. Nine of the ten
consumers only ever wanted to *open* the drawer.

## 2607.40.0 — Build the catalog without asking four hundred times

"Build the catalog" on the Missing page sweeps several hundred titles out of TMDB
and merges them into the canon. The merge asked the database about each candidate
one at a time — once for the existing canon row, and again for the film itself
whenever a curated entry arrived without a title. Two lookups per candidate,
sequentially, inside the request the owner is watching a spinner on.

Both are now read once for the whole sweep, chunked at five hundred, the same
shape the ingest writers and the scoring loop already use.

**406 statements for 200 candidates → 7.** Free on the SQLite the tests run
against, which is why it survived; a network round trip each against a hosted
database, which is the difference between a moment and a minute on the one screen
where the wait is unavoidable and visible.

The pin's negative control asserts two hundred rows were actually written, since
a merge that wrote nothing would satisfy any statement budget perfectly.

## 2607.39.0 — Say when it is the database, and keep credentials out of URLs

### A refusing database is not a bug in this app

A hosted database can stop accepting queries for reasons that have nothing to do
with Sift: a connection limit, a suspended compute, an exhausted free-tier
transfer allowance. All of them arrive as the same exception, and all of them
used to surface as a bare **"Internal Server Error"** on one screen and a spinner
that never resolved on another — from the browser, indistinguishable from the app
being broken.

Those now return **503** with a plain sentence: the database is refusing queries,
Sift itself is running, go and look at the provider's dashboard. That is the
difference between "something is broken" and knowing where to look. The negative
control matters as much as the pin: a handler that caught everything would turn
ordinary responses into 503s and make a healthy app look permanently down.

### Credentials no longer travel in URLs

An `<img>`, a download link and a WebSocket cannot send a header, so posters, CSV
exports and the scan socket all carried `?token=` — and a query string is recorded
by every proxy it passes, kept in browser history, and stored by shared caches.
What travelled there was the **thirty-day credential that opens the entire API**.

Tokens now carry a scope. URLs get a separate one that lasts fifteen minutes and
opens nothing but the asset it was minted for; every other route requires a full
session token. A token recovered from an access log is both expired and useless
against the API. The poster response also changed from `Cache-Control: public` to
`private`, since a shared cache has no business keeping a copy of a URL that
contains a credential.

Tokens issued before scopes existed carry no scope field and are still read as
session tokens, so nobody is signed out by this. If the short-lived token is
unavailable for any reason the session token stands in exactly as before — a
failure here must never mean a page of broken thumbnails.

Mutation-verified in both directions: not enforcing the scope, never granting
asset scope, and giving asset tokens a thirty-day life each turn a pin red.

## 2607.38.0 — Three more places the interface was quietly wrong

**The audit log said nothing had happened.** `Activity` destructured two of the
four values its hook returns, so a failed fetch left `data` null and the page
rendered "No activity yet — actions you approve or that run autonomously will
appear here." That page's own header calls it the trust surface. If a delete has
just executed and the request fails, the app states the delete never happened,
which is the worst available answer from the one screen whose job is to be
believed. It now says the log could not be loaded, says explicitly that this is
not the same as an empty log, and offers a retry. While loading it shows the
skeleton rows every other page uses, rather than a screen-reader-only paragraph
and a blank panel.

**A dropped page in the library vanished without trace.** The paging function had
a `try`/`finally` and no `catch`, and the page counter advanced *before* the
request. So when page three failed, the rejection was unhandled, the sentinel
scrolled on and asked for page four, and page three's titles were simply gone —
with nothing on screen to distinguish an incomplete list from the real end of the
data. The counter now rolls back on failure, the observer stops re-firing into
the same error, and the bottom of the list says the list is incomplete and offers
to load the rest. Titles already on screen stay put: a failed page is not a
failed list.

**The delete dialog opened with the delete button focused.** A stray Enter or
Space arriving on an autofocused Confirm approves a removal nobody chose, and
this dialog stands in front of every irreversible action in the app. Focus now
lands on Cancel. It is also trapped while the dialog is open — Tab used to walk
straight out into the page behind, leaving a modal that blocks visually but not
actually — and returns to whatever opened it on close, so working down a queue by
keyboard no longer means tabbing from the top of the page after every decision.

The frontend still has no test harness, so these are verified by `tsc` and a
production build. That remains the largest gap in this project's verification and
is recorded as such in `ARCHITECTURE.md`.

## 2607.37.0 — The poll that never stops

`/api/status` is requested every eight seconds for as long as a tab is open. Its
cost is not paid once; it is paid for ever, which makes it the only endpoint
where a handful of statements is worth arguing about.

It was doing the work twice over, at both ends.

**On the server**, eight separate `COUNT` statements — four of them over the same
`movies` table with different filters, so four scans to answer one question.
Conditional aggregates get all four numbers from a single pass, and the two watch
figures from another. **Ten statements per poll to five.**

**In the browser**, `TopNav` and `Dashboard` both call `useStatus`, and
`HealthDots` and `Dashboard` both call `useHealth`. Each hook holds its own state
and its own interval, so on the dashboard the server answered the identical
question twice every tick. Polled requests now share: one map of in-flight
promises, one of recent results, both keyed by endpoint, with a window set to
three quarters of the poll interval. A second consumer joins the tick already
running instead of doubling it, and successive ticks still fetch for real. No
cache library, about twenty lines.

**Together: 9,000 statements an hour with one tab open, down to 2,250.**

The pin carries a negative control on the numbers themselves — an endpoint
returning zeros would satisfy any statement budget perfectly, so it asserts that
all four filtered figures are still correct on a fixture built to distinguish
them. Mutation-verified: restoring the per-filter counts turns it red.

## 2607.36.0 — Recommendations you can actually browse

The list was capped three times over, and none of the caps were visible from the
screen.

**Twelve anchor films, twenty results each.** That is 240 raw candidates before
de-duplication and before removing what you already own — and anchors overlap
heavily, so the distinct pool came out far short of a couple of hundred. The
endpoint then returned **twenty-four** of them by default, and the page asked for
no more.

Sixty anchors now, and the API serves up to five hundred.

**"Recommended most" now means what it says.** The ranking key was
anchor-strength × TMDB position, so one highly-rated film's top pick could
outrank a title that several different films in the library independently
surfaced. The lead key is now how many of your own films recommended it; the
weighted score (with the Taste Profile's emphasis applied) breaks ties, and
``tmdb_id`` breaks those — so the order is stable between visits instead of
reshuffling under the cursor.

**It is computed during the scan, not on every page load.** Sixty anchor calls is
a reasonable thing to do inside a scan you are already waiting on, and an
unreasonable thing to make someone wait for every time they open the page — which
is what kept the anchor count low in the first place. Results land in a new
``recommendations`` table (a new table, so it deploys to a live database without
a migration) and the page reads them back. A failed refresh leaves the previous
list standing rather than blanking the shelf over a transient TMDB fault, and an
instance that has not rescanned yet still computes live once so nothing looks
broken in the meantime.

Storing replaces rather than merges: a recommendation is a claim about the
library as it is now, and a film you have since acquired has to leave the list
rather than linger because nothing thought to remove it.

Two of the new tests were rewritten after they passed against deliberately broken
code. The ranking test's fixture had the weighted score and the overlap count
agreeing, so it held under the old ranking too; it now makes them disagree
outright — the lone pick wins on score, loses on count. The pool test gave every
anchor its own private candidates, so de-duplication never bit and any anchor
count passed; anchors now overlap the way real ones do.

## 2607.35.0 — Stop paying to move data nothing reads

A hosted database meters **bytes moved**, not statements issued. Every previous
optimisation here counted round trips, because round trips were what made a scan
look hung. That measure is blind to a query that fetches one row containing a
kilobyte of text nobody looks at — and on a metered free tier, that is the bill.

Three reads in the scoring pass, which walks the entire library on every scan:

* **`select(Movie)` shipped all twenty-seven columns.** Scoring reads eleven of
  them, all small. The other sixteen include `overview`, `poster_url`, `genres`
  and `keywords` — roughly 1.4 KB per film against the 90 bytes that matter.
* **`select(Score)` shipped the whole `signals` JSON blob for every film**, to
  answer the question "does a row already exist for this id?". About a kilobyte
  each, fetched and discarded.
* **`select(ScoreV2)` did the same**, twice over, once for the write and once
  for the previous band that hysteresis needs. That one was introduced two
  releases ago by this project, which is the point: the existing statement-count
  pins all stayed green while the transfer doubled.

Scoring now selects the eleven columns it uses into a `ScoredMovie` tuple, reads
the two score tables as keys (plus the two band columns hysteresis needs), and
writes both in chunked bulk statements rather than a flush per film.

**Modelled against a five-thousand-film library: 21.2 MB → 3.9 MB of reads per
scan, about five and a half times less.** At a two-hourly autoscan that is the
difference between 7.6 GB and 1.4 GB a month, against a free allowance of 5 GB.

The new pin asserts the *shape* — that no statement mentions `movies.overview`,
`movies.poster_url`, `movies.genres`, `scores.signals` or `scores_v2.signals` —
because a byte count cannot be measured on SQLite, where all of this is free.
Both halves are mutation-verified: restoring either the full-row movie read or
the signals blob turns it red. It carries the usual negative control that two
hundred films were actually scored, since a scorer that does nothing reads no
wide columns at all.

## 2607.34.0 — Five ways the review screens told you the wrong thing

All five are moments where the interface said something untrue, and none of them
looked like a bug from the code.

**A failed request read as an empty queue.** The Junk page caught every fetch
error with `setItems([])`, so a dead Plex connection, an expired token or a 500
produced the green "All caught up — nothing is flagged for removal" state. This
is the one screen whose emptiness is meant to be good news, which makes it the
worst possible place to collapse "I could not answer" into "there is nothing to
do". A failure now says so and offers to retry, in the same error panel the TV
and Canon lists already use.

**Staged and live looked identical.** Every red "Approve removal" button rendered
the same whether the server would delete files or merely log the intent. The page
knew — it fetches the flag on mount — but only ever showed it inside the confirm
dialog, one step *after* the decision. The mode is now a pill beside the heading
on both Junk and Storage. After a session in staged mode, an undifferentiated red
button teaches you that red buttons are harmless.

**"Change" was offered on a file that no longer existed.** A completed live
removal collapsed to a row with a Change link, which put the row back into a
fully actionable state — including a working Approve button — for a file that was
gone. It reads as an undo next to the only irreversible action in the app. That
row now links to the audit entry instead. Staged removals and Keeps still change,
because those genuinely can.

**Re-running the AI review re-ticked everything you had spared.** Both the review
and the "Load all" path rebuilt the selection from the whole response, so working
through two hundred rows and unticking a dozen, then loading the rest, silently
re-selected all twelve and grew a destructive selection rather than shrinking it.
Refetching now adds only titles that have no decision yet.

**Storage always showed its generic error.** It read `.detail` from a thrown
`ApiError`, which carries the server's message on `.message` — so the specific
reason ("Plex not configured", "no snapshot") was discarded every single time.
The same file gets it right twenty lines further down, which is what marks it as
a slip rather than a decision.

The frontend has no test harness, so these are verified by `tsc --noEmit` and a
production build only. That gap is worth closing and is recorded as such rather
than papered over.

## 2607.33.0 — Delete the scaffolding

Nothing here changes what the app does. It removes documents that described work
that has since been done, and consolidates what was left.

**Gone, because they described a build that has already happened:**
`docs/GAME_PLAN.md` (the pre-build spec, superseded by `docs/ARCHITECTURE.md`,
which describes the system as it actually is); `docs/design/HANDOFF.md` and the
195 KB `Sift.prototype.html` it introduced, both superseded by the shipped
frontend; `docs/design/CANON_BUNDLE_HANDOFF.md`, which was install instructions
for a bundle that is installed; and the nine `docs/optimization/CYCLE_0*.md`
plans, which planned work whose outcomes are recorded a directory up. A plan for
finished work is not history, it is a document that disagrees with the code.

**Consolidated.** `CLAUDE.md` and `STATE.md` were two files answering one
question — what is settled here and why — so they are now `docs/ENGINEERING.md`.
The second root changelog moved to `docs/optimization/HISTORY.md`, next to the
loop's own log and metrics, which also moved out of a tool-specific dot
directory. The repo root is now five files instead of eight, and every document
in it is one somebody would open.

**The canon build scripts are runnable again.** All five hardcoded an absolute
path from the machine they were first run on, so none of them would have worked
for anyone. They now take `CANON_WORK_DIR`, and a `tools/canon/README.md`
records what produces what and in which order — which matters, because those
scripts are the only account of where the ten thousand canon titles came from.

Cross-references were followed rather than left dangling: what pointed at a
removed file now points at what replaced it, and the two entries in
`ARCHITECTURE.md`'s "known gaps" that had since been fixed are gone from it.

## 2607.32.0 — Three reads that grew with the library

Three places did work proportional to the whole library to answer a question
about a handful of things. All three are invisible on the SQLite the tests run
against, where a round trip is free, and all three are the dominant cost against
hosted Postgres, where it is a network hop. This is the 2607.15.1 lesson turning
up in three more places, so each now carries a structural pin rather than a
memory.

**Listing duplicates queried per group** — two statements each, the film and then
its copies. `find` runs twice on every load of the Storage screen (directly, and
again through the reclaim ledger) at a limit of a thousand, so a library with a
few hundred duplicated films paid for it in the thousands. **64 statements for 60
groups → 4**, and it no longer grows with the number of duplicates, which is the
thing the feature exists to surface — so it was worst exactly where it mattered
most. Copies are now read in one ordered pass, so a group's copies come back the
same way every request instead of in whatever order the database chose.

**Watch history wrote per row** — one SELECT per film per Plex user, so a
four-person household with two thousand watched titles issued up to eight
thousand sequential statements on every scan. The television half of the same
write already preloaded; this was the film half, missed at the time.
**123 statements for 120 rows → 3.**

**The strand guard read the whole `media_files` table** to check two paths, then
filtered in Python. That is one statement, so a statement count would have called
it healthy — but it ships every row in the table over the wire on every reclaim
action, and a thirty-thousand-episode library pays that to ask about a pair of
files. The cost grows forever while the request stays the same size. Now two
reads scoped to the request: which titles the requested paths belong to, then how
many files those particular titles hold. Its pin asserts the *shape* — no
unfiltered read of `media_files` — because the count was never what was wrong.

Each pin carries a negative control asserting the work still happened, since a
function that returns nothing satisfies any statement budget perfectly.

## 2607.31.0 — Close an unauthenticated file read, and score in shadow

### The serious one

Anyone who knew this instance's address could read any file on the server,
without logging in.

The route that serves the built UI checked containment with
`candidate.is_relative_to(dist)`. That comparison is **lexical** — it inspects
path segments and never resolves `..` — so `../../../etc/passwd` satisfied it.
The `is_file()` check beside it *does* resolve `..`, at the OS level, and
cheerfully said yes. Each check looked correct in isolation; together they served
whatever the second one could find. A browser collapses a literal `../` before
sending, which is why this never showed up by hand, but `%2e%2e` survives the
client, is decoded by the server, and is not re-normalised.

The file that matters is `/proc/self/environ`. On a hosted instance that is the
signing key, the database URL and every stored API key, which makes credential
encryption at rest irrelevant — the key and the ciphertext came through the same
hole. The path is now resolved before it is compared, and the containment check
finally means what it says.

**Rotate the credentials on any instance that has been publicly reachable.** The
fix closes the door; it cannot un-disclose anything already read.

### The rest of the same audit

* **The setup wizard was a window, not a wall.** Its only guard was "no account
  exists yet", so whoever reached a fresh instance first got the account and the
  owner got a 409 — and the window reopened every time the settings table came up
  empty. Where a static server token is configured, which the hosted Blueprint
  generates, creating the account now requires it.
* **The schema is no longer public.** `/openapi.json`, `/docs` and `/redoc` were
  served to anonymous callers, handing over every route, every request body and
  the exact build version. There is no second audience for that here.
* **The username is no longer public.** Login refuses on an unknown username
  before it checks the password, and the rate limiter is keyed by username, so
  publishing the real one turned a two-dimensional guess into a one-dimensional
  one. A signed-in caller still gets it; Settings renders it.
* **The static token is compared in constant time.** `==` on a string
  short-circuits at the first differing byte. Every other secret comparison in
  the codebase already used `compare_digest`; this was the outlier.
* **The Ollama connection test honours the URL guard.** It built its own HTTP
  client, so it was the one path that could be aimed at cloud metadata. Private
  ranges stay allowed — that is where a local Ollama lives.
* **Source maps are out of the production bundle**, and `routes_shows` is no
  longer registered twice.

### Scoring, second opinion

`scores_v2` now computes on every scan, in its own table, and changes nothing.

v1 blends signals additively: every signal pushes the same number, so enough
small pushes add up to a removal. v2 states the asymmetry as arithmetic instead —
obscurity is the only thing that presses toward deletion, and protection
multiplies it away:

```
score = 100 · clamp(pressure · (1 − protection) + w_q · quality_deficit)
```

Full protection zeroes any amount of obscurity pressure; zero protection leaves
it untouched. There is no combination of weak signals that condemns a film
somebody actually watched. Three consequences, each a v1 bug made structural: a
never-played title cannot be condemned, and neither can one abandoned eight
minutes in; quality is capped below a third of the smaller real signal, so a
famously bad film stays; and a title with thin evidence returns `insufficient`
rather than guessing.

It also reads the audit trail for the first time — a film you *asked for* and
never watched is a different thing from one nobody wanted, and from watch history
alone those look identical.

Bands move only on a 3-point margin, so a title stops flapping in and out of the
queue as votes tick over. Cutoffs are 70/50 against v1's 60/40, which visibly
shrinks the queue — which is exactly why none of it is shown yet.
`GET /api/junk/shadow-diff` lists every title the two disagree about, with both
scores. The golden set checks the rules; the shadow diff checks the judgement, on
your library rather than on cases chosen to prove a point. Cutover stays a
separate, deliberate decision.

Twenty-four new tests. Every negative control mutation-verified: reverting the
traversal fix turns four of them red, and the engagement-floor control was
rewritten after the first version of it passed against a deliberately broken
implementation.

## 2607.30.0 — Request the essential canon, a handful at a time

The Canon tab gains one batch action: request the next few essential films you do
not own, strongest claim first.

**The count is the entire safety story, so it is bounded three ways.** Tier 1
alone is over four thousand entries and ten thousand films is fifty to eighty
terabytes, which makes an unbounded batch button a disk incident one click away.
So: the server caps any request at fifty however many are asked for; the caller
must name a number rather than being offered an "all" that quietly means four
thousand; and the button arms on the first click and only files on the second,
like every other action that changes something outside Sift.

The dry-run floor applies exactly as it does to a single request. A staged
instance records the intent and sends nothing, and says so on the button rather
than reporting a success that did not happen.

Each title becomes its own audited action. A batch is a convenience for the person
clicking, not a different kind of write — and one title being unavailable does not
abandon the rest, which would leave the batch neither done nor undone.

## 2607.29.0 — A Canon tab, and the last whole-table read in the scan

**Missing gains a Canon tab.** The canon films not on your server, strongest
claim first, filterable by tier. The coverage line reports how many are still
being matched up rather than a bare "N of 10,000" — the canon is reconciled with
the library a few hundred titles per scan, so early on the list is shorter than
the truth and a plain figure would read as complete.

Renamed on the way in: the app already had a canon, the smaller list Sift builds
for itself from TMDB charts and serves at `/api/missing/canon`. The imported list
is `ValidatedCanon` throughout the client, and both carry a comment saying which
is which. Two things called canon in one codebase is a trap for whoever reads it
next.

**The last unscoped preload in the ingest path.** `_persist_plex_shows` read every
row of the shows table in order to write one section's worth. It runs once per TV
library section rather than per batch, so the cost was linear rather than
quadratic — but a library with several sections still re-read every show for each
of them. That closes every finding from the audit that ran alongside the
scan-slowdown fix.

## 2607.28.0 — The validated canon, and the shield it gives owned films

Ten thousand films worth owning, assembled outside the app from Criterion,
Wikipedia's cult list, award records and an IMDb consensus sweep, with the design
documents and regeneration tooling behind them.

The canon is a fact about cinema rather than about this household, and that is
what lets it answer both of Sift's questions at once. A canon film not owned is
something to acquire. A canon film owned is something the junk queue must leave
alone — otherwise the Missing page recommends acquiring the very title the Junk
page proposed deleting.

**The shield.** Tiers 1–3 — curated, award and consensus entries — join the set
whose recognition is floored, which is the existing mechanism that stops obscurity
condemning a Criterion title. Tier 4 stays out on purpose: it is fame-fill, and a
famous film nobody in the house watches is precisely what the junk queue exists to
surface. Absence from the canon remains evidence of nothing; ten thousand films is
not every good film.

**Resolution is the load-bearing step.** The canon arrives keyed by IMDb id and
the library is keyed by TMDB id, so nothing can be compared until the two are
reconciled. The TMDB client gains an exact `find_by_imdb` lookup, where a title
search would be a guess between remakes ten thousand times over. Resolution is
budgeted at 400 per scan and ordered by tier, so if the budget only ever covers
part of the list it covers the part that matters most. A miss is a counted attempt
rather than a verdict.

**Two read surfaces**, both backend for now: canon coverage, and the unowned canon
ranked `(tier, -votes, tmdb_id)`. Only resolved entries appear — an unresolved one
is not "missing", it is unknown, and listing it would invite acquiring a film
already on the shelf. Coverage reports its unresolved remainder for the same
reason: the figure is a floor while resolution catches up, and should not read as
complete.

`CanonEntry` is a new table rather than columns on an existing one, because
`create_all` adds tables on a live database and never adds columns. Seeding
inserts in bulk: ten thousand rows added one at a time is ten thousand round trips
on the first scan, which against a hosted database is close to a minute and
indistinguishable from a stall. 10,002 statements became 1,733.

## 2607.27.0 — Read a collection's members once, not once per collection

Two places fetched each collection's members with a query of their own, inside a
loop over every collection: the Collections page, on every load, and the scan's
finalize phase, on every scan. Members are now read once and grouped.

Fourteen reads become three for a twelve-collection library, and the count no
longer grows with the number of collections. That costs nothing on the SQLite the
tests run against and one network round trip apiece on the hosted database — the
same shape 2607.15.1 was about.

The ordering moved with the query rather than being dropped. Members were fetched
with `ORDER BY year NULLS LAST`, and a collection reads as a timeline, so the
order is part of the answer. It is now sorted in code, with the id as a tie-break
so a collection whose members share a year does not rearrange itself between
requests.

## 2607.26.0 — Show each series at the resolution most of it is in

**Every show was listed at its rarest resolution.** The quality shown against each
series came from a dict comprehension over rows ordered by count descending — and
a comprehension keeps the *last* value written, so the final row, the least common
resolution, won every time. A series of nineteen 1080p episodes and one stray 480p
displayed as 480p. It now takes the most common, with ties breaking toward the
lower rung as they do elsewhere: the reading that never overstates what a library
is held in.

**The show list also re-scanned the whole library on every page.** Both grouped
aggregates join media files to episodes to seasons, and neither was limited to the
page being asked for, so scrolling a thirty-thousand-episode library read all of
it twice per page. The page is now fetched first and the aggregates cover only the
shows on it. The library-wide size total became a plain sum, computed once on the
first page like the row count beside it.

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

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): decisions restore with preview-by-default apply
flow, a 500 MB poster-cache ceiling with oldest-first eviction, a Library
section filter, persisted view/sort preferences, Esc-cancellable Ask,
connection-URL normalization (scheme + trailing slashes), restorable dismissed
must-haves, reduced-motion-aware gauges, dated backup filenames, and announced
loading states.

## 2607.7.0 — Optimization Cycle 07

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): live per-phase scan counts in the panel, poster
fallbacks labeled with the title's initial, a decisions backup download
(keep-overrides + dismissals + thresholds), a vendor chunk (app bundle 222 kB →
59 kB), junk cap disclosure with bounded Load-all, expand-all signal
breakdowns, folding curated lists, cancellable Ask requests, health dots
linking to Settings, and accessible gauge labels.

## 2607.6.0 — Optimization Cycle 06

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): real Ask compare mode (both tandem providers
phrase one retrieval, side by side, graceful degradation), Activity movie-id
drawer links + expandable scan receipts, collapsed decided junk rows, junk
score/size sort, a recently-added dashboard strip, a version footer, ownership
pills in global search, slow-request logging (paths only — tokens never reach
logs), and a wizard readiness line.

## 2607.5.0 — Optimization Cycle 05

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): route-level error boundary, chooseable Radarr add
defaults (root folder + quality profile with stale-safe fallback), streaming
CSV export of the filtered library, 375 px mobile fixes (search row, no CTA
wrap), memoized grid tiles/posters, a tiny Ask answer formatter, one-click
collection fill with progress, bounded poster warm-up after completed scans,
username prefill at login, and skip-to-content + labeled landmarks.

## 2607.4.0 — Optimization Cycle 04

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): cached health sweep (774 ms → 10 ms polls) with
save/test invalidation, visibility-aware polling, page-1-only list aggregates,
meaningful ring gauges (new `watched_titles` count), a search no-match row,
scan-failure Retry, `g`-chord keyboard navigation + `?` shortcuts overlay,
honest not-set-up vs unreachable connection states, Ask focus retention +
New conversation, and a growing bounded Activity window.

## 2607.3.0 — Optimization Cycle 03

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): auditable health score with named deductions,
cached status queue counts with exact write-path invalidation, login
brute-force guard (per-account 429 + Retry-After), mid-session sign-out on dead
tokens, sortable table columns (+ Size column), junk reclaimable-disk totals,
shared error toasts on failed mutations, snapshot freshness + stale hint,
route-level code splitting (272 kB → 216 kB main bundle), and multi-select
toolbar accessibility.

## 2607.2.0 — Optimization Cycle 02

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): state-driven dashboard attention cards with live
junk/must-have queue counts, taste-profile weights that actually steer
recommendations (bounded reorder, zero-weight equivalence test-pinned), inline
global-search results with poster thumbs + latest-wins fetches, Ask suggestion
chips built from the library profile, scan history on Activity, security headers
(nosniff / DENY / same-origin referrer), empty states with a next-step action,
async poster decoding, gzip for large JSON responses, and `junk_flagged` /
`musthave_pending` status counts that always match their pages.

## 2607.1.0 — Optimization Cycle 01

Ten reviewed changes (log:
`docs/optimization/HISTORY.md`): password-manager-friendly login + ephemeral-host
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
