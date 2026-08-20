// Everything you have said no to, and the way back.
//
// "Remembered forever" is a promise made to the suggestion engine: nothing in
// here is ever proposed again, by the built-in list, by TMDB, or by an AI. It is
// not a promise made against you. A decision you cannot review is not a decision,
// it is a black hole — and on a list of twenty-five thousand films, a mis-click
// is a matter of when rather than whether.
//
// This is the only screen those titles appear on, and the only place they can be
// brought back.

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/Toast";
import { EmptyState, Poster, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { IgnoredItem } from "@/lib/types";

const tmdbMovieUrl = (tmdbId: number) => `https://www.themoviedb.org/movie/${tmdbId}`;

export function SetAsideList({ onRestored }: { onRestored?: () => void }) {
  const [items, setItems] = useState<IgnoredItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const toastError = useToast();

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const r = await api.ignoredTitles();
      setItems(r.items);
      setTotal(r.total);
    } catch (e: unknown) {
      // Emptying the list on a failed read would say "you have never set anything
      // aside", which is both untrue and the most reassuring possible lie.
      setLoadError(
        (e as { message?: string })?.message ||
          "Couldn't load what you've set aside. This is not the same as having set nothing aside.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function restore(item: IgnoredItem) {
    setBusy(item.tmdb_id);
    try {
      await api.unignoreTitle(item.tmdb_id);
      // Removed from this list rather than reloaded: the row is gone from the
      // server's answer either way, and a reload would cost a round trip to be
      // told what we already know.
      setItems((prev) => prev.filter((x) => x.tmdb_id !== item.tmdb_id));
      setTotal((n) => Math.max(0, n - 1));
      onRestored?.();
    } catch {
      toastError(`Couldn't bring “${item.title || item.tmdb_id}” back.`);
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <div className="panel p-4" aria-busy="true">
        <span className="sr-only" role="status">
          Loading what you&rsquo;ve set aside…
        </span>
        <div className="flex flex-wrap gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[162px] w-[108px]" />
          ))}
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="panel p-4 text-sm" style={{ color: "var(--junk)" }}>
        <p className="font-semibold">{loadError}</p>
        <button
          onClick={() => void load()}
          className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
        >
          Try again
        </button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="panel">
        <EmptyState
          title="Nothing set aside"
          hint="Films you pass on with “Not for me” collect here. They are never suggested again — by the built-in list, by TMDB, or by any AI you have connected — until you bring them back."
        />
      </div>
    );
  }

  return (
    <div className="panel p-4">
      <p className="mb-3 text-xs text-fg3">
        {total.toLocaleString()} set aside. These are never suggested again anywhere — bringing
        one back returns it to the list at its usual place.
      </p>
      <div className="flex flex-wrap gap-3">
        {items.map((m) => (
          <div key={m.tmdb_id} style={{ width: 108 }}>
            <a
              href={tmdbMovieUrl(m.tmdb_id)}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full text-left"
              title="View on TMDB"
            >
              <div className="relative aspect-[2/3] overflow-hidden rounded-md">
                <Poster
                  tmdbId={m.tmdb_id}
                  alt=""
                  label={m.title}
                  className="h-full w-full opacity-60"
                />
              </div>
              <p className="mt-1 truncate text-[11px] text-fg3">{m.title || m.tmdb_id}</p>
            </a>
            <button
              onClick={() => void restore(m)}
              disabled={busy === m.tmdb_id}
              aria-label={`Suggest ${m.title || m.tmdb_id} again`}
              className="mt-1 w-full rounded-md border border-line py-1 text-[11px] font-semibold text-accent hover:bg-bg2 disabled:opacity-70"
            >
              {busy === m.tmdb_id ? "…" : "Bring back"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
