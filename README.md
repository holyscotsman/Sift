# Sift

**Repo:** <https://github.com/holyscotsman/Sift>

> A lightweight, non-Docker companion to **Butlarr**. Sift runs on a laptop (or any
> machine) and reaches your self-hosted movie server over the network. It reads
> **Plex + Radarr** (plus **Tautulli + TMDB + Overseerr**), learns your taste, then
> finds **missing** movies worth owning, flags **junk** worth removing, helps
> **organize**, and answers **plain-English questions** about your library.

---

## What Sift actually does

Think of Sift as a smart assistant that sits on top of the movie server you
already run. In plain terms:

- **Tells you what you're missing.** Not just "gaps in a franchise" — Sift keeps a
  running list of movies worth owning (top-rated classics, blockbusters, cult
  favorites, award winners) and shows you exactly which ones aren't in your library
  yet. One click requests them.
- **Tells you what's worth deleting.** It scores every movie in your library for
  how "junk" it is (low quality, rarely watched, no real following) and explains
  *why* in plain language — but it never deletes a file on its own. A real delete
  always waits for you to say yes.
- **Answers questions about your library.** Ask things like "what horror movies
  have I not watched?" and get an answer grounded in your actual data, not a guess.
- **Keeps your library tidy.** Duplicate/upgrade candidates, stale watch-history
  signals, and collection gaps all surface in one place instead of five different
  apps.

## How the workflow works, step by step

1. **Connect your services** (one-time setup wizard): point Sift at Plex and
   Radarr (required), and optionally Tautulli, TMDB, Overseerr, and an AI provider
   (local Ollama and/or Anthropic Claude). Everything is entered in the browser and
   saved — you never touch a config file.
2. **Sift scans.** It reads your Plex library, Radarr's catalog, Tautulli's watch
   history, and TMDB's metadata, then caches a private snapshot in a local SQLite
   database. Nothing is written back during a scan — it's read-only.
3. **You browse the results.** The **Missing** tab shows must-watch movies you
   don't own; **Junk** shows removal candidates with a plain-language reason;
   **Collections** shows sets you own part of; **Ask** answers free-text questions.
4. **You take action, one click at a time.** Requesting a movie routes through
   Overseerr (if you've connected it) or straight to Radarr otherwise. Adding,
   monitoring, and unmonitoring happen right away and are logged. **Deleting a
   file is the one action that always stops and asks you to confirm first** — no
   exceptions, enforced by the code itself, not just a setting.
5. **Rescan whenever you like.** Your decisions (kept titles, dismissed
   suggestions, taste preferences) are remembered across rescans.

Sift and Butlarr split the work cleanly: Butlarr manages files on the server
(integrity, storage, renames); Sift is the portable "brain" that reads metadata
from all four services and decides what's missing, what's junk, and what's worth
asking about. **They share no database** — each talks to the same APIs
independently.

---

## Open the app

Sift is a **local** web app — the FastAPI backend serves the UI on your own
machine (bound to `localhost` by design, since it holds your Plex/Radarr keys, so
there is no public URL by default). Once it's running, open:

**▶ [http://127.0.0.1:8756](http://127.0.0.1:8756)**

Run it from source (packaged `pipx install sift` / `uvx sift` lands in Phase 4):

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
- To reach it from another device on your network, front it with **Tailscale** or a
  reverse proxy rather than exposing it publicly (see [Remote access](#remote-access)).

---

## Autonomy & safety tiers

| Action | Reversible? | Policy |
|---|---|---|
| Add / monitor in Radarr (or request via Overseerr) | Yes | Autonomous, audited. |
| Unmonitor / remove-from-catalog (no file delete) | Yes | Autonomous, audited. |
| **File delete** (`deleteFiles=true`) | **No** | **Requires explicit approval. Never auto.** |

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
TMDB ──┘                                     actions/engine ─► Radarr / Overseerr
                                              (add/monitor/request autonomous;
                                               delete is always approval-gated)
```

Sources are authoritative for different facts:

| Source | Authoritative for |
|---|---|
| **Plex** | Library membership ("owned"), what's playable, per-user watch state, kids-vs-adult separation. |
| **Radarr** | Monitored/wanted, quality profile + cutoff, file presence — a management overlay, not the library itself. |
| **Tautulli** | Watch history: plays, last-played, completion. |
| **TMDB** | External ratings + vote counts, collection / keyword / person graph. |
| **Overseerr** | Optional request front door — when connected, requests flow through its own approval pipeline. |

## Remote access

Sift binds to `127.0.0.1` by default and token-gates its API. To reach a remote
Radarr/Plex safely, use **Tailscale** (or a reverse proxy) rather than exposing
anything publicly.

## Project layout

```
backend/sift/
  main.py          FastAPI app + static serving
  config.py        TOML/.env settings
  cli.py           `sift serve|scan|init`
  db/              SQLAlchemy models, session, Alembic migrations
  clients/         plex / radarr / tautulli / tmdb / overseerr on a shared base
  ingest/          normalize (canonical identity) + pipeline (resumable scan)
  actions/         propose/approve/execute engine (delete = approval-gated)
  services/        health, audit, canon, config store
  api/             routes_* + ws
backend/tests/     pytest suite (mocked clients, negative controls)
frontend/          React + Vite + TS (Dashboard, Library, Junk, Missing,
                   Collections, Ask, Taste Profile, Settings, Activity)
```

See `STATE.md` for the current resume point and `CHANGELOG.md` for full history.

## License

MIT.
