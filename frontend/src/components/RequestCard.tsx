// Shared pieces for every "not in your library yet" surface (Missing, Collections):
// a poster card that links out to TMDB, and request buttons that file the add
// through the server's preferred route — Overseerr when configured, Radarr
// otherwise, staged when the server floor says dry-run.

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Poster } from "@/components/ui";
import { api } from "@/lib/api";
import type { ActionRecord } from "@/lib/types";

const tmdbMovieUrl = (tmdbId: number) => `https://www.themoviedb.org/movie/${tmdbId}`;

function requestOutcome(action: ActionRecord): string {
  if (action.payload?.via === "overseerr") {
    // Overseerr already had it — worth saying so rather than implying we just
    // filed it, but it's still a success and the title is on its way.
    return action.payload?.already_requested ? "Already requested ✓" : "Requested ✓";
  }
  return action.dry_run ? "Request staged" : "Added ✓";
}

export function RequestButton({ tmdbId, title }: { tmdbId: number; title: string }) {
  const [label, setLabel] = useState("Request");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  async function send(e: React.MouseEvent) {
    e.stopPropagation();
    setState("busy");
    try {
      const action = await api.requestMovie(tmdbId, title);
      setState("done");
      setLabel(requestOutcome(action));
    } catch {
      setState("idle");
      setLabel("Retry");
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
//
// `confirmFirst` turns it into a two-step: one click arms, the next sends. Worth it
// wherever the set is large enough that an accidental click would flood Overseerr
// with requests you'd then have to cancel by hand.
export function RequestAllButton({
  items,
  label: idleLabel,
  confirmFirst = false,
  onDone,
}: {
  items: { tmdb_id: number; title: string }[];
  label?: string;
  confirmFirst?: boolean;
  onDone?: () => void;
}) {
  const [state, setState] = useState<"idle" | "armed" | "busy" | "done">("idle");
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
    onDone?.();
  }
  const text =
    state === "busy"
      ? label
      : state === "armed"
        ? `Send ${items.length} requests?`
        : (idleLabel ?? `Request all missing (${items.length})`);
  return (
    <button
      onClick={() => {
        if (confirmFirst && state === "idle") setState("armed");
        else void requestAll();
      }}
      disabled={state === "busy"}
      className={`ml-auto rounded-pill border px-3 py-1 text-xs font-semibold hover:bg-bg2 disabled:opacity-70 ${
        state === "armed" ? "border-accent text-accent" : "border-line text-accent"
      }`}
    >
      {text}
    </button>
  );
}

// Poster card for a title you don't own: artwork links out to TMDB (the drawer
// would 404 — the title isn't in the snapshot), with a Request button below.
//
// `onIgnore` adds the other half of the decision. A card that has been acted on
// stays on screen, dimmed, rather than vanishing: on an endless list a card that
// disappears under the cursor takes the next one's place, and the click that was
// already on its way lands on something else entirely. It is gone from the next
// load, which is where "remembered forever" actually lives.
export function RequestCard({
  tmdbId,
  title,
  year,
  subtitle,
  voteAverage,
  width = 108,
  onIgnore,
  onUndoIgnore,
}: {
  tmdbId: number;
  title: string;
  year: number | null;
  subtitle?: string;
  voteAverage?: number | null;
  width?: number;
  onIgnore?: (tmdbId: number, title: string) => Promise<void>;
  onUndoIgnore?: (tmdbId: number) => Promise<void>;
}) {
  const [ignored, setIgnored] = useState(false);
  const [busy, setBusy] = useState(false);
  const toastError = useToast();

  async function ignore() {
    if (!onIgnore) return;
    setBusy(true);
    try {
      await onIgnore(tmdbId, title);
      setIgnored(true);
    } catch {
      toastError(`Couldn't set “${title}” aside — it will still be suggested.`);
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!onUndoIgnore) return;
    setBusy(true);
    try {
      await onUndoIgnore(tmdbId);
      setIgnored(false);
    } catch {
      toastError(`Couldn't bring “${title}” back.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ width }} className={ignored ? "opacity-40" : undefined}>
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
      {ignored ? (
        <button
          onClick={() => void undo()}
          disabled={busy || !onUndoIgnore}
          className="mt-1 w-full rounded-md border border-line py-1 text-[11px] font-semibold text-fg3 hover:bg-bg2 disabled:opacity-70"
        >
          {busy ? "…" : "Not for me · undo"}
        </button>
      ) : (
        <>
          <RequestButton tmdbId={tmdbId} title={title} />
          {onIgnore && (
            <button
              onClick={() => void ignore()}
              disabled={busy}
              aria-label={`Never suggest ${title} again`}
              className="mt-1 w-full rounded-md border border-line py-1 text-[11px] font-semibold text-fg3 hover:bg-bg2 disabled:opacity-70"
            >
              {busy ? "…" : "Not for me"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
