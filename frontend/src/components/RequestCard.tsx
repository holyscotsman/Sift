// Shared pieces for every "not in your library yet" surface (Missing, Collections):
// a poster card that links out to TMDB, and request buttons that file the add
// through the server's preferred route — Overseerr when configured, Radarr
// otherwise, staged when the server floor says dry-run.

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Poster } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { ActionRecord } from "@/lib/types";

const tmdbMovieUrl = (tmdbId: number) => `https://www.themoviedb.org/movie/${tmdbId}`;

function requestOutcome(action: ActionRecord): string {
  if (action.payload?.via === "overseerr") {
    return action.payload?.request_status === "already_requested" ? "Already requested" : "Requested ✓";
  }
  return action.dry_run ? "Request staged" : "Added ✓";
}

export function RequestButton({ tmdbId, title }: { tmdbId: number; title: string }) {
  const [label, setLabel] = useState("Request");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const toastError = useToast();
  async function send(e: React.MouseEvent) {
    e.stopPropagation();
    setState("busy");
    try {
      const action = await api.requestMovie(tmdbId, title);
      setState("done");
      setLabel(requestOutcome(action));
    } catch (err) {
      setState("idle");
      setLabel("Retry");
      const detail = err instanceof ApiError ? err.message : "couldn't reach the server";
      toastError(`Requesting “${title}” failed — ${detail}`);
    }
  }
  return (
    <button
      onClick={send}
      disabled={state !== "idle"}
      className="mt-1 w-full rounded-md border border-line py-1 text-[11px] font-semibold text-accent hover:bg-bg2 disabled:opacity-70"
    >
      {state === "busy" ? "…" : label}
    </button>
  );
}

// Fill a whole set in one click — sequential, visible progress, a failure stops
// the walk and names the title. Same server-side routing as a single request.
export function RequestAllButton({ items }: { items: { tmdb_id: number; title: string }[] }) {
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [label, setLabel] = useState("");
  const toastError = useToast();
  if (items.length < 2 || state === "done") {
    return state === "done" ? (
      <span className="ml-auto text-xs font-semibold text-fg3">{label}</span>
    ) : null;
  }
  async function requestAll() {
    setState("busy");
    let sent = 0;
    for (const item of items) {
      setLabel(`Requesting ${sent + 1}/${items.length}…`);
      try {
        await api.requestMovie(item.tmdb_id, item.title);
        sent += 1;
      } catch {
        toastError(`Requesting “${item.title}” failed — ${sent} of ${items.length} were sent.`);
        break;
      }
    }
    setLabel(sent === items.length ? `All ${sent} requested ✓` : `${sent} requested`);
    setState("done");
  }
  return (
    <button
      onClick={() => void requestAll()}
      disabled={state === "busy"}
      className="ml-auto rounded-pill border border-line px-3 py-1 text-xs font-semibold text-accent hover:bg-bg2 disabled:opacity-70"
    >
      {state === "busy" ? label : `Request all missing (${items.length})`}
    </button>
  );
}

// Poster card for a title you don't own: artwork links out to TMDB (the drawer
// would 404 — the title isn't in the snapshot), with a Request button below.
export function RequestCard({
  tmdbId,
  title,
  year,
  subtitle,
  voteAverage,
  width = 108,
}: {
  tmdbId: number;
  title: string;
  year: number | null;
  subtitle?: string;
  voteAverage?: number | null;
  width?: number;
}) {
  return (
    <div style={{ width }}>
      <a
        href={tmdbMovieUrl(tmdbId)}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full text-left"
        title={`${subtitle ? `${subtitle} — ` : ""}view on TMDB`}
      >
        <div className="relative aspect-[2/3] overflow-hidden rounded-md">
          <Poster tmdbId={tmdbId} alt="" label={title} className="h-full w-full opacity-90" />
          {voteAverage != null && voteAverage > 0 && (
            <span className="absolute right-1 top-1 rounded-sm bg-black/60 px-1 text-[10px] font-semibold text-white backdrop-blur">
              {voteAverage.toFixed(1)}
            </span>
          )}
        </div>
        <p className="mt-1 truncate text-[11px] text-fg3">
          {title} {year ? `· ${year}` : ""}
        </p>
        {subtitle && <p className="truncate text-[10px] text-fg3/80">{subtitle}</p>}
      </a>
      <RequestButton tmdbId={tmdbId} title={title} />
    </div>
  );
}
