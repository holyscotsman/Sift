# Sift

> A lightweight, non-Docker companion to **Butlarr**. Sift runs on a laptop (or any
> machine) and reaches a self-hosted movie server over the network. It reads
> **Plex + Radarr** (plus **Tautulli + TMDB**), builds a taste profile, then finds
> **missing** movies, flags **junk** worth removing, helps **organize**, and answers
> **natural-language questions** about the library.

Butlarr stays the heavy, on-server, file-plane tool. Sift is the portable metadata
brain. They share **no database** — they talk to the same APIs independently.

## 🚀 Open the app

Sift is a web app you run yourself — the FastAPI backend serves the UI. It binds
to `localhost` by default, because it holds your Plex/Radarr keys; hosting it
somewhere reachable is supported and documented, and puts it behind sign-in. Once
it's running locally, open:

**▶ [http://127.0.0.1:8756](http://127.0.0.1:8756)**

Run it from source:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                                   # backend
npm --prefix frontend ci && npm --prefix frontend run build   # build the UI
sift serve                                                # then open the link above
```

- **☁️ Host it on the web** (reach it from anywhere, free — Render/Fly/Docker):
  **[docs/DEPLOY.md](docs/DEPLOY.md)**
- **📖 Full local setup** (credentials, first scan, remote access):
  **[docs/SETUP.md](docs/SETUP.md)**
- **Source / repo:** <https://github.com/holyscotsman/Sift>
- To reach it from another device on your network, front it with **Tailscale** or a
  reverse proxy rather than exposing it publicly (see [Remote access](#remote-access)).

---

## What's in it

Ten screens, all driven off one resumable scan:

| Screen | What it answers |
|---|---|
| **Dashboard** | What state is the library in, and what needs attention. |
| **Library** | Everything owned, filtered and sorted, paged as you scroll. |
| **Missing** | Films worth owning that you don't have — the validated canon minus your shelf. |
| **Collections** | Sets you own part of, with the gaps requestable in one click. |
| **Junk** | What deserves removing, scored deterministically, one approval at a time. |
| **Storage** | Where the disk actually went: duplicates, oversized files, TV seasons that weigh more than their peers, and a target-driven plan to get a given amount back. |
| **Ask** | Natural-language questions, answered over your own library. |
| **Taste Profile** | What you actually watch, and the recommendations that follow from it. |
| **Activity** | Every proposed and executed action, audited. |
| **Settings** | Connections, thresholds, scan schedule, backup and restore. |

Underneath:

- Six async API clients (Plex, Radarr, Sonarr, Tautulli, TMDB, Overseerr) on a
  shared retry / backoff-with-jitter / rate-limiting base.
- A resumable, checkpointed, **streamed** ingestion pipeline — films and TV,
  written as it reads rather than accumulated, so a large library cannot exhaust
  memory mid-scan.
- An action engine with the **golden safety invariant**: a file delete is only
  ever issued after an explicit, recorded, per-item approval, and `dry_run` is
  the server's floor — a client may opt into staging but can never force a live
  write. Enforced by tests, and by there being exactly one chokepoint.
- Session auth with scoped asset tokens, encrypted credential storage, and no
  anonymous schema.
- `sift` CLI: `serve`, `scan`, `init`.

Runs on SQLite locally; set `DATABASE_URL` and it runs on Postgres (see
[docs/DEPLOY.md](docs/DEPLOY.md)).

See `docs/ENGINEERING.md` for the settled decisions and `CHANGELOG.md` for history.

---

## The two planes

| Plane | Who owns it | What it touches |
|---|---|---|
| **Metadata plane** | **Sift** (runs anywhere) | Read Plex/Radarr/Tautulli/TMDB APIs, cache a snapshot, analyze, recommend. |
| **File plane** | **Butlarr** (on the server) | Integrity, storage, renames — **out of scope for Sift.** |

Sift can *request* a Radarr-side delete, but that path is gated behind explicit
approval and never runs automatically.

## Autonomy & safety tiers

| Action | Reversible? | Policy |
|---|---|---|
| Add / monitor in Radarr | Yes | Autonomous, audited. |
| Unmonitor / remove-from-catalog (no file delete) | Yes | Autonomous, audited. |
| **File delete** (`deleteFiles=true`) | **No** | **Requires explicit approval. Never auto.** |

---

## Quick start (development)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp sift.toml.example sift.toml       # edit connections
cp .env.example .env                 # add your tokens/keys

sift init          # interactive scaffolder (writes sift.toml if missing)
sift serve         # start the API + UI at http://127.0.0.1:8756
sift scan          # run a headless ingestion scan
```

Run the gates CI runs — all four have to be green:

```bash
ruff check backend          # lint
mypy                        # strict, backend
pytest                      # backend suite, with negative controls
cd frontend && npm test     # component suite (vitest + testing-library)
cd frontend && npm run build  # typecheck + production build
```

Every new test pin gets a **negative control** — a test that fails if the fix is
overapplied — and controls are *mutation-verified*: break the implementation,
confirm the test goes red, restore. A pin nobody has seen fail is a pin nobody
should trust.

## Architecture

```
Plex ──┐
Radarr ┤
Sonarr ┼─► ingest/pipeline ─► database snapshot ─► analysis ─► FastAPI ─► React UI
Tautulli┤   (resumable, streamed)                     │
TMDB ──┘                                       actions/engine ─► Radarr (add/monitor)
                                                       │        ─► file jobs, claimed
                                                       │           by an agent on the
                                                       │           media box
                                                 delete is approval-gated,
                                                 per item, dry-run by default
```

The snapshot is SQLite locally and Postgres when `DATABASE_URL` is set.

Sources are authoritative for different facts:

| Source | Authoritative for |
|---|---|
| **Radarr** | Owned/monitored film catalog, quality profile + cutoff, file presence. |
| **Sonarr** | The canonical episode file, series quality profiles, monitored state — and where a downgrade is written back. |
| **Plex** | What's actually playable, per-user watch state, kids-vs-adult separation, and *duplicates* — the only source that reports several files for one title. |
| **Tautulli** | Watch history: plays, last-played, completion. |
| **TMDB** | External ratings + vote counts, collection / keyword / person graph. |

## Remote access

Sift binds to `127.0.0.1` by default and puts its API behind sign-in. To reach a
remote Radarr/Plex safely, use **Tailscale** (or a reverse proxy) rather than
exposing anything publicly. If you want Sift itself reachable from anywhere,
[docs/DEPLOY.md](docs/DEPLOY.md) covers hosting it.

## Project layout

```
backend/sift/
  main.py          FastAPI app + static serving
  config.py        TOML/.env settings
  cli.py           `sift serve|scan|init`
  db/              SQLAlchemy models, session, Alembic migrations
  clients/         plex / radarr / sonarr / tautulli / tmdb / overseerr on a shared base
  ingest/          normalize (canonical identity) + pipeline (resumable, streamed scan)
  analysis/        every verdict the app reaches — junk scoring, the validated
                   canon, duplicates, bitrate baselines, TV size and suitability,
                   the reclaim ledger, recommendations. Deterministic arithmetic
                   over stored facts; an LLM never decides correctness.
  actions/         propose/approve/execute engine (delete = approval-gated)
  services/        auth, health, autoscan, poster cache, secret storage, canon seeding
  api/             routes_* + ws
backend/tests/     pytest suite (mocked clients, negative controls)
frontend/src/
  pages/           one file per screen, each with a .test.tsx beside it
  components/      shared UI, including the confirm dialog every delete goes through
  lib/             api client, hooks, providers
  test/            harness — the real provider stack, so a test renders what ships
```

## License

MIT.
