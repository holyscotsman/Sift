// Movie detail drawer — slides in from the right over any screen. Reads
// /api/movies/{id}; shows ratings, the Sift score + rationale, watch history, and
// a raw-metadata escape hatch.

import { useEffect, useState } from "react";

import { ConfirmModal } from "@/components/ConfirmModal";
import { Pill, Poster } from "@/components/ui";
import { api } from "@/lib/api";
import { useDrawer } from "@/lib/drawer";
import type { MovieDetail } from "@/lib/types";

function MovieActions({ movie }: { movie: MovieDetail }) {
  const [dryRun, setDryRun] = useState(true);
  const [monitored, setMonitored] = useState(movie.monitored);
  const [busy, setBusy] = useState<null | "mon" | "rm">(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    api.getActionsConfig().then((a) => setDryRun(a.dry_run)).catch(() => setDryRun(true));
  }, []);

  if (movie.radarr_id == null) {
    return (
      <p className="mt-4 rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-fg3">
        Not managed by Radarr — Sift can only monitor or remove titles that are in Radarr.
      </p>
    );
  }

  async function setMon(next: boolean) {
    setBusy("mon");
    setMsg(null);
    try {
      const a = await api.proposeAction({
        type: next ? "monitor" : "unmonitor",
        movie_tmdb_id: movie.tmdb_id,
        dry_run: false,
        actor: "user", // a manual toggle from the drawer is a user action, not autonomous
      });
      const done = await api.executeAction(a.id);
      setMonitored(next);
      setMsg(
        done.dry_run
          ? `${next ? "Monitor" : "Unmonitor"} staged`
          : next
            ? "Now monitoring"
            : "Unmonitored",
      );
    } catch {
      setMsg("Action failed — check the Radarr connection.");
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("rm");
    setMsg(null);
    try {
      const a = await api.proposeAction({
        type: "delete",
        movie_tmdb_id: movie.tmdb_id,
        payload: { delete_files: true, title: movie.title },
        dry_run: false,
      });
      await api.approveAction(a.id);
      const done = await api.executeAction(a.id);
      setMsg(done.dry_run ? "Removal staged" : "Removed from Radarr");
    } catch {
      setMsg("Removal failed — check the Radarr connection.");
    } finally {
      setBusy(null);
      setConfirm(false);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <button
        onClick={() => setMon(!monitored)}
        disabled={busy !== null}
        className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
      >
        {busy === "mon" ? "…" : monitored ? "Unmonitor" : "Monitor"}
      </button>
      <button
        onClick={() => setConfirm(true)}
        disabled={busy !== null}
        className="rounded-md px-3 py-1.5 text-xs font-bold disabled:opacity-60"
        style={{ background: "var(--junk)", color: "var(--accent-fg)" }}
      >
        Remove
      </button>
      {msg && <span className="text-xs text-fg2">{msg}</span>}
      <ConfirmModal
        open={confirm}
        title="Remove from Radarr?"
        confirmLabel={dryRun ? "Stage removal" : "Remove file"}
        busy={busy === "rm"}
        onCancel={() => setConfirm(false)}
        onConfirm={remove}
        body={
          <p className="text-sm text-fg2">
            {dryRun
              ? "Staged (dry-run) — this records the removal but deletes nothing. Enable live writes in Settings › Autonomy to actually remove."
              : "This tells Radarr to delete the file. It cannot be undone."}
          </p>
        }
      />
    </div>
  );
}

// Protected (keep-override) badge with the only undo surface once a title has left
// the Junk list: click to unprotect so it can be flagged again.
function ProtectedPill({ tmdbId }: { tmdbId: number }) {
  const [on, setOn] = useState(true);
  if (!on) return null;
  return (
    <button
      onClick={() =>
        void api.setKeepOverride(tmdbId, false).then(() => setOn(false)).catch(() => {})
      }
      title="You marked this Keep — it's never flagged as junk. Click to unprotect."
    >
      <Pill tone="keep">Protected ✕</Pill>
    </button>
  );
}

function fmtSize(bytes: number | null): string {
  return bytes ? `${(bytes / 1e9).toFixed(1)} GB` : "—";
}
function bandTone(band: string): "junk" | "borderline" | "keep" {
  return band === "junk" ? "junk" : band === "borderline" ? "borderline" : "keep";
}

export function MovieDrawer() {
  const { movieId, close } = useDrawer();
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [raw, setRaw] = useState(false);

  useEffect(() => {
    if (movieId === null) {
      setMovie(null);
      return;
    }
    setLoading(true);
    setRaw(false);
    api
      .movie(movieId)
      .then(setMovie)
      .catch(() => setMovie(null))
      .finally(() => setLoading(false));
  }, [movieId]);

  if (movieId === null) return null;

  return (
    <div className="fixed inset-0 z-[90]" role="dialog" aria-modal="true" aria-label="Movie details">
      <div
        className="absolute inset-0 bg-black/50"
        style={{ animation: "sift-backdrop var(--dur) ease both" }}
        onClick={close}
      />
      <div
        className="glass absolute right-0 top-0 h-full w-full max-w-[560px] overflow-y-auto"
        style={{ animation: "sift-drawer var(--dur) var(--ease-spring) both" }}
      >
        <div className="relative h-28 overflow-hidden bg-bg2">
          {movie && <Poster tmdbId={movie.tmdb_id} alt="" className="h-full w-full opacity-60" />}
          <div className="absolute inset-0" style={{ background: "linear-gradient(to top, var(--bg-1s), transparent)" }} />
        </div>
        <button
          onClick={close}
          aria-label="Close"
          className="absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full bg-black/40 text-white backdrop-blur hover:bg-black/60"
        >
          ✕
        </button>

        {loading || !movie ? (
          <div className="p-6 text-fg3">{loading ? "Loading…" : "Not found."}</div>
        ) : (
          <div className="p-6">
            <h2 className="font-display text-2xl font-extrabold">{movie.title}</h2>
            <p className="mt-1 text-sm text-fg3">
              {movie.year ?? "—"}
              {movie.runtime ? ` · ${movie.runtime} min` : ""}
              {movie.library_section ? ` · ${movie.library_section}` : ""}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              {movie.in_plex && <Pill tone="keep">In Plex</Pill>}
              {movie.monitored && <Pill tone="accent">Monitored</Pill>}
              {movie.quality && <Pill>{movie.quality}</Pill>}
              {movie.is_kids && <Pill tone="borderline">Kids</Pill>}
              {movie.keep_override && <ProtectedPill tmdbId={movie.tmdb_id} />}
            </div>

            <MovieActions key={movie.tmdb_id} movie={movie} />

            {movie.sift_score && (
              <div className="mt-5 rounded-lg border border-line bg-bg2 p-4">
                <div className="flex items-center gap-2">
                  <span className="eyebrow">Sift score</span>
                  <Pill tone={bandTone(movie.sift_score.band)}>
                    {movie.sift_score.band} · {Math.round(movie.sift_score.junk_score)}
                  </Pill>
                </div>
                <p className="mt-2 text-sm text-fg2">{movie.sift_score.rationale}</p>
              </div>
            )}

            {movie.ratings.length > 0 && (
              <div className="mt-5">
                <span className="eyebrow">Ratings</span>
                <div className="mt-2 flex gap-4">
                  {movie.ratings.map((r) => (
                    <div key={r.source}>
                      <div className="font-display text-lg font-bold">{r.value.toFixed(1)}</div>
                      <div className="text-xs uppercase text-fg3">
                        {r.source} · {r.votes ?? 0}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {movie.watch_history.length > 0 && (
              <div className="mt-5">
                <span className="eyebrow">Watch history</span>
                <div className="mt-2 divide-y divide-line text-sm">
                  {movie.watch_history.map((w, i) => (
                    <div key={i} className="flex justify-between py-1.5">
                      <span className="text-fg2">
                        {w.plex_user}
                        {w.is_kids_account ? " (kids)" : ""}
                      </span>
                      <span className="text-fg3">
                        {w.plays} play(s)
                        {w.completion_pct != null ? ` · ${Math.round(w.completion_pct * 100)}%` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {movie.overview && (
              <div className="mt-5">
                <span className="eyebrow">Overview</span>
                <p className="mt-2 text-sm text-fg2">{movie.overview}</p>
              </div>
            )}

            {movie.keywords.length > 0 && (
              <div className="mt-5 flex flex-wrap gap-1.5">
                {movie.keywords.slice(0, 12).map((k) => (
                  <span key={k} className="rounded-pill bg-bg2 px-2 py-0.5 text-[11px] text-fg3">
                    {k}
                  </span>
                ))}
              </div>
            )}

            <div className="mt-6">
              <button
                onClick={() => setRaw((v) => !v)}
                className="text-xs font-semibold text-accent"
              >
                {raw ? "Hide" : "Advanced / raw metadata"}
              </button>
              {raw && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-line bg-panel p-3 font-mono text-[11px] text-fg2">
                  {JSON.stringify(movie, null, 2)}
                </pre>
              )}
            </div>

            <div className="mt-6 flex gap-2">
              <span className="text-xs text-fg3">
                Size {fmtSize(movie.file_size)} · TMDB {movie.tmdb_id}
                {movie.imdb_id ? ` · ${movie.imdb_id}` : ""}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
