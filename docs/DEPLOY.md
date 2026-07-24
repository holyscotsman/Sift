# Deploying Sift to the web (Render, free)

This hosts Sift on **Render** so it's reachable from anywhere at an `https://…`
URL — no machine of your own required. Render's server talks to your web-reachable
Radarr/Plex directly (no browser CORS/mixed-content limits apply), and your keys stay
server-side.

> Render is the friendliest click-through host. The same `Dockerfile` also runs on
> **Fly.io**, **Railway**, or **Koyeb** if you prefer one of those.

---

## Before you start — gather your details

- **Radarr URL + API key** — e.g. `http://holysplexrequests.duckdns.org:7878` and the
  key from Radarr → *Settings → General → Security → API Key*.
- **TMDB key** (recommended) — [themoviedb.org → Settings → API](https://www.themoviedb.org/settings/api).
- **Plex / Tautulli** (optional) — can be added later; skip them for the first deploy.

The code is on the `claude/sift-webapp-setup-2qmxsn` branch of
`github.com/holyscotsman/Sift`. You'll point Render at that branch (or merge it to
`main` first and use `main`).

---

## Steps

1. **Create a Render account** at <https://render.com> and choose **"Sign in with
   GitHub."** Authorize Render to access your repositories (you can limit it to just
   the `Sift` repo).

2. **New Blueprint.** In the Render dashboard: **New → Blueprint**. Pick the `Sift`
   repo and the `claude/sift-webapp-setup-2qmxsn` branch. Render reads `render.yaml`
   and proposes one **free** web service called `sift`.

3. **Fill in the environment values** Render prompts for:

   | Key | Value |
   |---|---|
   | `SIFT_RADARR__BASE_URL` | your Radarr URL, e.g. `http://holysplexrequests.duckdns.org:7878` |
   | `SIFT_RADARR__API_KEY` | your Radarr API key |
   | `SIFT_TMDB__API_KEY` | your TMDB key |
   | `SIFT_PLEX__BASE_URL` / `SIFT_PLEX__TOKEN` | *(optional — leave blank for now)* |
   | `SIFT_TAUTULLI__BASE_URL` / `SIFT_TAUTULLI__API_KEY` | *(optional — leave blank)* |

   `SIFT_SERVER__API_TOKEN` is **generated for you** — you don't type it.

4. **Apply / Deploy.** Render builds the Docker image (a few minutes the first time)
   and starts the service. When it's live you'll get a URL like
   `https://sift-xxxx.onrender.com`.

5. **Get your access token.** In the service's **Environment** tab, reveal
   `SIFT_SERVER__API_TOKEN` and copy it.

6. **Open the app** at your Render URL. You'll see Sift's **unlock screen** — paste
   the token. (It's stored in that browser, so you only do this once per device.)

7. **Run a scan.** The connection dots (top-right) should show Radarr green; click
   **Run scan**. The Dashboard and Library fill in when it finishes.

That's it — bookmark the URL on your phone and you're set.

---

## Make your setup persist (free — do this first)

Render's free tier has an **ephemeral disk**: the default `sift.db` resets on every
redeploy/restart, so your **login and saved service keys disappear**. Point Sift at a
free, persistent Postgres and it survives forever — same Render URL, no code changes.

1. Create a free database at **[neon.tech](https://neon.tech)** (or any hosted
   Postgres — Supabase works too). Neon's free tier is persistent with no expiry.
2. Copy its **connection string** — it looks like
   `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`.
3. In Render → your Sift service → **Environment**, set
   `SIFT_DATABASE__URL` to that string and save (Render redeploys).

That's it — Sift creates its tables on first boot. Now run the setup wizard **once**;
your account, connections, and scans stick across every future redeploy.

> Prefer to stay on SQLite? A Render **Disk** (paid Starter plan) with
> `SIFT_DATABASE__PATH=/data/sift.db`, or a **Fly.io** deploy with a free volume, also
> persist. The Postgres route above is the simplest free option.

**Your keys are encrypted in there.** A persistent database is a database that keeps
your Plex/Radarr/TMDB keys around indefinitely — including in its backups — so Sift
encrypts them before writing. There is nothing to set up: the blueprint generates a
`SIFT_SECRET_KEY`, and if you never set one Sift falls back to your access token. The
key lives in Render's environment, never in the database. Settings › Account confirms
it ("Saved service keys are encrypted at rest"). If you already had keys saved in
plaintext, the next boot seals them in place — no action needed. See **Rotating the
encryption key** below.

What this does and doesn't cover: it protects your credentials wherever the *data*
travels without the environment — database backups, replicas, snapshots, a leaked
connection string, an exported dump. It is not a substitute for guarding the running
instance: anyone who can reach your Sift URL **with a valid session or your access
token** can still use the app, and the app necessarily decrypts keys to talk to your
services.

## Good to know (free tier)

- **It sleeps when idle.** Free services spin down after ~15 minutes of no traffic;
  the next visit takes ~30s to wake. Fine for personal use.
- **Thumbnail cache** still lives on the ephemeral disk, so posters re-fetch from TMDB
  after a redeploy — that's automatic and only affects first paint. Your data (in the
  Postgres above) is what matters and it persists.
- **Updating.** With `autoDeploy` on, pushing new commits to the branch redeploys
  automatically — safe now, because your data lives in Postgres, not the container.

## Security

- The access token is the only thing standing between the public internet and your
  Radarr, so **keep it secret** and don't disable it. Rotate it anytime by changing
  `SIFT_SERVER__API_TOKEN` in Render (then re-unlock with the new value).
- Your Radarr is exposed over plain HTTP with just its API key. Hosting Sift doesn't
  change that; putting Radarr behind HTTPS + a login later would harden the whole setup.
- Only `add` / `monitor` / `unmonitor` can run autonomously; **a file delete is never
  issued without your explicit in-app approval.**
- **Service keys are encrypted at rest.** Anything you enter in the wizard/Settings is
  sealed before it's stored, with key material that lives only in the environment
  (`SIFT_SECRET_KEY`, else `SIFT_SERVER__API_TOKEN`). The session signing secret is
  sealed the same way — in the clear it would let anyone holding a database dump forge
  a login, which would hand them every other credential through the running app.
- **Rotate the access token if it ever leaks.** It is a bearer credential: the export
  endpoints accept it as a `?token=` query parameter, so it can end up in browser
  history and platform request logs. If you rely on it as the encryption fallback,
  rotating it also re-keys your stored secrets — see below. Setting an explicit
  `SIFT_SECRET_KEY` decouples the two, which is why the blueprint generates one.

### Rotating the encryption key

Change `SIFT_SECRET_KEY` in Render and restart. Everyone is signed out (session tokens
are signed with a secret derived from it) and previously saved service keys can no
longer be read — Sift reports those services as not-configured rather than failing, and
you re-enter them once in Settings. **You cannot lock yourself out:** logging back in
with your password mints a fresh signing secret automatically. Your account, library,
and decisions are untouched.

*Adding* a `SIFT_SECRET_KEY` to an instance that has been running on the access-token
fallback is safe and needs no re-entry: Sift still reads values sealed under the old
material and quietly re-seals them under the new key on the next boot.

## Removals: staged vs. live

Sift ships **staged (dry-run) by default** — approving a removal records it in the
audit log but **does not touch any files**. This is the safe default for a hosted
instance: even someone with your token can't delete anything.

When you're ready to let Sift actually issue deletes to Radarr, set one env var in
Render:

| Variable | Value |
|---|---|
| `SIFT_ACTIONS__DRY_RUN` | `false` |

With it `false`, an **approved** removal is sent to Radarr (`deleteFiles=true`) — the
Junk screen then says **"Removed"** instead of **"Removal staged"**, and warns you in
the confirm dialog that the delete is real and irreversible. The approval gate still
applies: nothing deletes without you clicking through. Leave it unset (or `true`) to
stay in the audit-only staging mode.
