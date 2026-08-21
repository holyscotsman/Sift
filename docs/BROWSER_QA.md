# Browser QA

What a real browser found that the unit suite structurally cannot, and what is
waiting on a human decision.

Run it with:

```sh
sift serve
SIFT_PASS=... npm --prefix frontend run audit:layout   # layout, themes, console
SIFT_PASS=... npm --prefix frontend run audit:a11y     # axe, contrast, labels
```

Both exit non-zero on a finding, so either can gate a release. `audit:layout`
writes a screenshot per screen per theme into `frontend/shots/` (git-ignored) —
looking at those is the part no script does.

## Why this exists separately from the unit suite

jsdom has no layout and no compositing. It cannot see:

- text clipped by its container,
- a row that overflows its card,
- the colour a translucent pill actually ends up sitting on,
- or a number rendered as `0.0 GB`.

Every one of those renders as "present and correct" to a unit test. Three real
defects have come out of this pass so far, and none of them could have been found
any other way:

| Found | Fixed in |
|---|---|
| The junk pill measured 5.83:1 against the page background and **4.48:1** against the card it is really drawn on | 2607.100.0 |
| The genres/runtime caption on Missing was truncated to `Essential · Joel Coe…` and had never been visible to anyone | 2607.98.0 |
| A 40 MB file rendered as **`0.0 GB`** — five of six size formatters could not express anything under 50 MB, which is the entire tier-0 category on Storage | 2607.121.0 |
| A preference read straight out of `localStorage` put an unmatched value on `data-theme`, silently rendering the default palette | 2607.121.0 |

The last two were found in the same run. The theme one surfaced by accident: the
audit harness wrote a JSON-quoted value where the app stores raw, and **three
entire theme passes rendered the default palette while reporting success.** The
audit now asserts the applied theme on every screen, so that cannot happen quietly
again.

## Current state — clean

Ten screens (`/`, `/library`, `/missing`, `/collections`, `/junk`, `/storage`,
`/ask`, `/profile`, `/activity`, `/settings`) at 1440×1000 and 390×844, in dark,
light and neon — **forty screenshots, all four passes verified to have applied
the theme they claimed**:

- **No horizontal page overflow** anywhere. Wide content scrolls inside its own
  container, which is the rule.
- **No text clipped without an ellipsis or a `title`.** Deliberate `truncate` is a
  design choice and is not reported; silent clipping is the defect and there is
  none.
- **No literal `undefined`, `NaN`, `[object Object]` or `Invalid Date`** on any
  screen — the check that would have caught the four mismatched test fixtures if
  it had existed earlier.
- **No console errors** beyond poster 404s and the scan websocket, both of which
  are artefacts of an unconfigured local instance rather than defects.

One error *was* real and is fixed: rebuilding the frontend under a running server
threw `Failed to fetch dynamically imported module`. Every page is a lazy import
and the Update button on Settings is an in-app action, so any tab open across an
update hits it — and the boundary's primary button was "Try again", which
re-renders the same dead import. Now handled as its own failure (2607.123.0). A
test artefact that turned out to describe the real update path.

## Waiting on a human

### 1. Inline controls at 16px tall

Not fixed, because control sizing is a design decision and the project standard
says visual work is not done until it is signed off.

The app's controls are a consistent ~28px pill, which is below the 44px touch
standard but deliberate and uniform. What stands out from that baseline:

| Screen | Control | Size |
|---|---|---|
| Activity | `#603` / `#608` (the TMDB id link on a timeline row) | 33×16 |
| Activity | `Payload` | 53×16 |
| Junk | `Signal breakdown` | 139×16 |
| Junk | `Clear selection` | 89×16 |

The Activity pair is the one worth a look: two 16px-tall buttons sitting inline on
the same row, which is the geometry that gets mis-tapped. The Junk row checkbox
already shows the fix — a 16px input inside a `-m-3 h-11 w-11` label, so the
visual stays small and the target does not.

**Decision needed:** raise these to a 44px hit area the same way, or accept them.

### 2. A number split from its unit across a line

The Junk header wraps as `~32.3` / `GB reclaimable.` — the figure separated from
its unit by a line break. A non-breaking space inside `fmtSize` fixes it
everywhere at once, but it changes the return value of a formatter with assertions
across several test files.

**Decision needed:** worth the churn, or leave it.

### 3. Still outstanding from the definition of done

- A **live scan against the real server** with real Plex/Radarr/Sonarr
  credentials. Everything above ran against a seeded fixture, which exercises
  layout but proves nothing about real data volumes or real titles.
- **Human sign-off on the screenshots themselves.** The audit checks what can be
  measured; whether the screens look right is not one of those things.
