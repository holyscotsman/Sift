# Changelog

Versioning scheme: `YYMM.major.patch`.

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
