# Sift

> A lightweight, non-Docker companion to **Butlarr**. Sift runs on a laptop (or any
> machine) and reaches a self-hosted movie server over the network. It reads
> **Plex + Radarr** (plus **Tautulli + TMDB**), builds a taste profile, then finds
> **missing** movies, flags **junk** worth removing, helps **organize**, and answers
> **natural-language questions** about the library.

Butlarr stays the heavy, on-server, file-plane tool. Sift is the portable metadata
brain. They share **no database** — they talk to the same APIs independently.

## 🚀 Open the app

Sift is a **local** web app — the FastAPI backend serves the UI on your own
machine (bound to `localhost` by design, since it holds your Plex/Radarr keys, so
there is no public URL). Once it's running, open:

**▶ [http://127.0.0.1:8756](http://127.0.0.1:8756)**

Run it from source (packaged `pipx install sift` / `uvx sift` lands in Phase 4):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                                   # backend
npm --prefix frontend ci && npm --prefix frontend run build   # build the UI
sift serve                                                # then open the link above
```

- **Source / repo:** <https://github.com/holyscotsman/Sift>
- To reach it from another device on your network, front it with **Tailscale** or a
  reverse proxy rather than exposing it publicly (see [Remote access](#remote-access)).

---

## Status

**Phase 0 — Skeleton + read-only ingestion** (in progress).

Implemented so far:

- Config loader (`sift.toml` + `.env` overrides, secrets as `SecretStr`).
- SQLite snapshot schema (SQLAlchemy 2.x models) + Alembic scaffolding.
- Four async API clients (Plex, Radarr, Tautulli, TMDB) on a shared retry /
  backoff-with-jitter / rate-limiting base.
- Resumable, checkpointed ingestion pipeline.
- Action engine with the **golden safety invariant**: a file delete is only ever
  issued after an explicit, recorded approval (enforced by a test).
- FastAPI app: `/api/health`, `/api/status`, `/api/scan`, `/api/movies`, and a
  `/ws/scan/{id}` live-progress socket.
- `sift` CLI: `serve`, `scan`, `init`.

See `STATE.md` for the current resume point and `CHANGELOG.md` for history.

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

Run the test suite:

```bash
pytest
```

## Architecture

```
Plex ─┐
Radarr ┼─► ingest/pipeline ─► SQLite snapshot ─► analysis ─► FastAPI ─► React UI
Tautulli┤                                          │
TMDB ──┘                                     actions/engine ─► Radarr (add/monitor;
                                                                delete is approval-gated)
```

Sources are authoritative for different facts:

| Source | Authoritative for |
|---|---|
| **Radarr** | Owned/monitored catalog, quality profile + cutoff, file presence. |
| **Plex** | What's actually playable, per-user watch state, kids-vs-adult separation. |
| **Tautulli** | Watch history: plays, last-played, completion. |
| **TMDB** | External ratings + vote counts, collection / keyword / person graph. |

## Remote access

Sift binds to `127.0.0.1` by default and token-gates its API. To reach a remote
Radarr/Plex safely, use **Tailscale** (or a reverse proxy) rather than exposing
anything publicly. A template lives in `docs/` (Phase 4).

## Project layout

```
backend/sift/
  main.py          FastAPI app + static serving
  config.py        TOML/.env settings
  cli.py           `sift serve|scan|init`
  db/              SQLAlchemy models, session, Alembic migrations
  clients/         plex / radarr / tautulli / tmdb on a shared base
  ingest/          normalize (canonical identity) + pipeline (resumable scan)
  actions/         propose/approve/execute engine (delete = approval-gated)
  services/        health, audit
  api/             routes_* + ws
backend/tests/     pytest suite (mocked clients, negative controls)
frontend/          React + Vite + TS (added once the design lands)
```

## License

MIT.
