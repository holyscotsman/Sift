# CLAUDE.md — Sift

Build guidance for Claude Code. Read this first, every session, then `STATE.md`.

---

## 1. What this project is

**Sift** is a portable, non-Docker companion to *Butlarr*. It runs anywhere (a
laptop), reaches a self-hosted movie server over the network, reads **Plex +
Radarr + Tautulli + TMDB**, caches a **SQLite snapshot**, then:

- finds **missing** movies (collection gaps + taste-based recommendations),
- flags **junk** worth removing (deterministic score; the LLM only explains it),
- helps **organize**, and answers **natural-language questions** grounded in the
  snapshot.

Butlarr owns the **file plane** (integrity, storage, renames) on the server. Sift
owns the **metadata plane** and runs anywhere. They share **no database**.

---

## 2. How work happens here

- **Build from the game plan** (`docs/GAME_PLAN.md`) — the phased MVP (Phases 0–4),
  then the 80 post-MVP tasks. Each phase has a **"Done when"** gate; do not advance
  until it is met.
- **Session entry point:** this file → `STATE.md` (resume point) → continue the
  current phase.
- Small, reviewable commits; **every behavior change ships with a test**; no
  destructive action path ships without a guarding test.

---

## 3. Golden safety rule (overrides everything except a worse safety risk)

**A file delete is only ever issued after an explicit, recorded user approval.**
This is a hard invariant enforced by `actions/engine.py` and locked by
`tests/test_actions_safety.py`. Adds/monitors/unmonitors may be autonomous (and are
audited); deletes may not. Never weaken this without a louder test.

---

## 4. Locked decisions

- **Name:** Sift.
- **Form factor:** local web app (FastAPI + browser UI), `uvx`/`pipx`-installable.
  No Docker required (an optional image is a parity nicety, not the primary path).
- **No filesystem access is ever assumed.** All analysis is API-only against the
  cached snapshot; the media server may be offline at any time — degrade gracefully.
- **Autonomy tiers:** add/monitor = autonomous; unmonitor/remove-from-catalog =
  autonomous + audited; **file delete = always explicit approval.**
- **Junk detection is hybrid:** deterministic, vote-weighted data decides the
  score; the LLM only *explains* it and is forbidden from overriding it.
- **Kids guardrail:** items in children's libraries are never auto-flagged for
  removal on adult-rating grounds; they carry a visible guard chip.
- **LLM:** provider abstraction (Local Ollama + Anthropic) with three modes
  (route-by-task / compare / race-fallback) and a separate embedding slot. AI is
  **never** used to decide correctness of a delete or a key fact.
- **Version scheme:** `YYMM.major.patch`.

---

## 5. Source-of-truth map (resolve conflicts by this table)

**Plex is the source of truth for library membership** (owner decision, overriding the
original game-plan default that made Radarr the catalog authority). A movie is "in the
library" / "owned" iff it's present in a Plex movie section (`movies.in_plex`). Radarr
is a **management overlay**, not the library definition.

| Source | Authoritative for |
|---|---|
| **Plex** | **Library membership + "owned" (`in_plex`)**, what's playable, per-user watch state, user ratings, kids-vs-adult separation. |
| **Radarr** | Monitored/wanted, quality profile + cutoff, TMDB collection membership, Radarr file state (`has_file`, for duplicate/upgrade analysis) — an overlay, not the library. |
| **Tautulli** | Watch history: plays, last-played, completion. |
| **TMDB** | External ratings + vote counts, collection / keyword / person graph. |

---

## 6. Architecture

- **Metadata plane only.** Ingest via async clients → SQLite snapshot → analysis →
  FastAPI → React UI. Actions go back to Radarr through one audited engine.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, async
  `httpx`. **Frontend:** React + Vite + TS + Tailwind, built to static assets and
  served by FastAPI at `/`.
- **Clients** share `clients/base.py` (retry/backoff-with-jitter, rate limiting,
  secret redaction). *Decision:* Sift talks to all four services with direct async
  `httpx` (not `plexapi`/`pyarr`) so the whole client layer is uniformly async,
  rate-limited, and mockable — see `STATE.md`.
- **Every action** passes through `actions/engine.py`, is recorded with a dry-run
  payload, and only `executed` per the autonomy tier above.

---

## 7. Hard rules for all work

- **Gates:** the test suite is the minimum ship gate. **Negative controls are
  mandatory** on new test pins (a delete-safety test must also prove the unsafe
  path is refused). **Never fabricate a green.**
- **Types:** type hints + `mypy --strict` on the backend; TypeScript strict on the
  frontend.
- **Secrets:** never commit secrets; `SecretStr` for tokens; redact from logs and
  error surfaces. Bind localhost by default; token-gate the API.
- **Performance:** flat-memory streaming ingestion; virtualized tables; target
  smooth handling of 10k+ movies. No unbounded in-memory accumulation in a scan.
- **Resilience:** every client has retry/backoff + rate limiting; a scan survives a
  mid-run server drop (checkpointed, resumable); the UI degrades when a source is
  offline.
- **Commits:** small, per-unit; keep the `YYMM.major.patch` version scheme; no
  timeline estimates in docs or commit messages.

---

## 8. Definition of done (per unit)

Implemented + tests (with negative controls where a safety/exclusion rule exists) +
green **reported honestly** + committed + `CHANGELOG.md` and `STATE.md` updated.
Visual/UI units are additionally queued for human visual sign-off and marked
"code-complete, visual-pending" until then.

---

## 9. Doc map

- `docs/GAME_PLAN.md` — the authoritative build spec (MVP phases + 80 tasks).
- `STATE.md` — resume point + working decisions.
- `CHANGELOG.md` — history under the `YYMM.major.patch` scheme.
- `README.md` — user-facing overview.
