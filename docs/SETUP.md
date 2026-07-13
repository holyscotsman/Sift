# Setting up Sift

Sift runs as a small web server on a machine that can reach your Plex + Radarr over
the network, and you open it in a browser. This walks through getting it running and
plugging in your services.

> **Where to run it.** Any always-on machine on the same network as Plex/Radarr is
> ideal — the box that already runs Plex/Radarr/Butlarr, a NAS, or a Raspberry Pi.
> Your laptop works too. To reach it from your phone or off the network, put
> [Tailscale](#reaching-it-from-other-devices) on that machine — don't expose it to
> the public internet.

---

## 1. Prerequisites

- **Python 3.12+**
- **Node 18+** (used once, to build the UI)
- **git**
- Network reachability to your Plex, Radarr, and (optionally) Tautulli, plus internet
  for TMDB.

## 2. Get the code

The app currently lives on the `claude/sift-webapp-setup-2qmxsn` branch (pull
request #1). Until that's merged into `main`:

```bash
git clone https://github.com/holyscotsman/Sift.git
cd Sift
git checkout claude/sift-webapp-setup-2qmxsn
```

## 3. Install the backend and build the UI

```bash
python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .

# Build the browser UI (the backend serves it). Needs Node.
npm --prefix frontend ci
npm --prefix frontend run build
```

## 4. Create the config files

```bash
sift init
```

This writes two files in the current folder:

- **`sift.toml`** — non-secret settings (which servers to talk to). Safe to keep.
- **`.env`** — your tokens/keys. **Never commit this** (it's git-ignored).

Open `sift.toml` and set each service's `base_url`. Open `.env` and paste the
matching secret. Set `enabled = false` in `sift.toml` for any service you don't use
(Tautulli and TMDB are optional; Radarr + Plex are the core).

### Where each value comes from

| Service | `base_url` (in `sift.toml`) | Secret (in `.env`) | How to get the secret |
|---|---|---|---|
| **Plex** | `http://<plex-host>:32400` | `SIFT_PLEX__TOKEN` | In Plex Web, open any movie → **⋯ → Get Info → View XML**; copy the `X-Plex-Token=…` value from the page URL. |
| **Radarr** | `http://<radarr-host>:7878` | `SIFT_RADARR__API_KEY` | Radarr → **Settings → General → Security → API Key**. |
| **Tautulli** (optional) | `http://<tautulli-host>:8181` | `SIFT_TAUTULLI__API_KEY` | Tautulli → **Settings → Web Interface → API** → enable, then copy the API key. |
| **TMDB** (optional) | *(built-in)* | `SIFT_TMDB__API_KEY` | [themoviedb.org](https://www.themoviedb.org/settings/api) → **Settings → API** → request a key; paste the **API Read Access Token** (v4, starts with `eyJ`) or the v3 key. |

Example `.env`:

```dotenv
SIFT_PLEX__TOKEN=xxxxxxxxxxxxxxxxxxxx
SIFT_RADARR__API_KEY=xxxxxxxxxxxxxxxxxxxx
SIFT_TAUTULLI__API_KEY=xxxxxxxxxxxxxxxxxxxx
SIFT_TMDB__API_KEY=eyJhbGciOi...
# Leave SIFT_SERVER__API_TOKEN blank for now — see the note in step 6.
```

If your children have separate Plex libraries, list them in `sift.toml` so they're
guarded from removal:

```toml
[plex]
kids_sections = ["Kids Movies", "Family"]
[tautulli]
kids_accounts = ["Kiddo"]
```

## 5. Start it and run the first scan

```bash
sift serve
```

Open **http://127.0.0.1:8756**. The five connection dots in the top-right should go
green (hover one to see the detail). Click **Run scan** — it reads Radarr, Plex,
Tautulli, and TMDB into a local snapshot; the Dashboard and Library fill in when it
finishes. You can also scan headlessly with `sift scan`.

Everything is stored in a single SQLite file (`sift.db` by default; change it with
`[database] path` in `sift.toml`).

## 6. A couple of notes

- **API token:** `sift.toml` supports a `SIFT_SERVER__API_TOKEN` that gates the API.
  Leave it **blank for now** — the bundled UI doesn't yet have a field to enter it
  (the Settings screen is still a placeholder), and binding to localhost already
  protects it. Token entry lands with the Settings screen.
- **Only `add`/`monitor`/`unmonitor` can run on their own; a file delete is never
  issued without your explicit approval** — that's a hard, tested guarantee.

## Reaching it from other devices

By default Sift listens only on `127.0.0.1`, so it's reachable only from the machine
it runs on. To use it from your phone or another computer **without exposing it to
the internet**, install [Tailscale](https://tailscale.com/) on the host and start
Sift bound to all interfaces:

```bash
sift serve --host 0.0.0.0
```

Then browse to `http://<machine-name>.<your-tailnet>.ts.net:8756` from any device on
your tailnet. (A reverse proxy like Caddy/Nginx works too if you already run one.)

## Troubleshooting

- **A connection dot is red** — check that service's `base_url` and secret, and that
  the host is reachable from where Sift runs. Hover the dot for the error detail, or
  call `curl http://127.0.0.1:8756/api/health`.
- **The page shows JSON, not the UI** — the frontend wasn't built. Re-run
  `npm --prefix frontend run build`, then restart `sift serve`.
- **`sift: command not found`** — activate the virtualenv (`source .venv/bin/activate`).
