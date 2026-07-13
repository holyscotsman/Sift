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

## Good to know (free tier)

- **It sleeps when idle.** Free services spin down after ~15 minutes of no traffic;
  the next visit takes ~30s to wake. Fine for personal use.
- **The snapshot is not persistent.** Free instances have an ephemeral disk, so the
  `sift.db` snapshot resets on each deploy/restart — just hit **Run scan** again.
  To keep it, attach a Render **Disk** (paid) and set `SIFT_DATABASE__PATH` to a path
  on it (e.g. `/data/sift.db`), or use a **Fly.io volume**.
- **Updating.** With `autoDeploy` on, pushing new commits to the branch redeploys
  automatically.

## Security

- The access token is the only thing standing between the public internet and your
  Radarr, so **keep it secret** and don't disable it. Rotate it anytime by changing
  `SIFT_SERVER__API_TOKEN` in Render (then re-unlock with the new value).
- Your Radarr is exposed over plain HTTP with just its API key. Hosting Sift doesn't
  change that; putting Radarr behind HTTPS + a login later would harden the whole setup.
- Only `add` / `monitor` / `unmonitor` can run autonomously; **a file delete is never
  issued without your explicit in-app approval.**
