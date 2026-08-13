// Missing — theatrical-scale films the PLEX library doesn't have. The backend
// keeps a private canon (TMDB top-rated + blockbusters + curated lists + gated
// curator picks) and this page shows only the difference: canon minus Plex.
// Radarr is deliberately ignored — wanted-but-not-downloaded still counts as
// missing. Requests route through Overseerr when configured, Radarr otherwise.

import { useEffect, useState } from "react";

import { RequestAllButton, RequestCard } from "@/components/RequestCard";
import { useToast } from "@/components/Toast";
import { EmptyState, Skeleton } from "@/components/ui";
import { ShowSuggestions } from "@/components/ShowSuggestions";
import { api } from "@/lib/api";
import type { CanonMovieItem } from "@/lib/types";

const FOLD = 30;

export function Missing() {
  const [tab, setTab] = useState<"movies" | "tv">("movies");
  const [items, setItems] = useState<CanonMovieItem[]>([]);
  const [total, setTotal] = useState(0);
  const [requestedTotal, setRequestedTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const toastError = useToast();

  function load() {
    return api
      .canonMissing()
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setRequestedTotal(r.requested_total);
      })
      .catch(() => setItems([]));
  }

  useEffect(() => {
    void load().finally(() => setLoading(false));
  }, []);

  async function refresh() {
    setRefreshing(true);
    setNote(null);
    try {
      const r = await api.canonRefresh();
      setNote(
        `Catalog refreshed — ${r.canon_written.toLocaleString()} titles in the canon` +
          (r.curator_added > 0 ? `, ${r.curator_added} new curator picks` : "") +
          `; ${r.missing_total.toLocaleString()} missing from your Plex library.`,
      );
      await load();
    } catch {
      toastError("The catalog refresh failed — check the TMDB connection.");
    } finally {
      setRefreshing(false);
    }
  }

  const visible = showAll ? items : items.slice(0, FOLD);

  const tabs = (
    <div className="mb-4 flex gap-1" role="tablist" aria-label="Missing kind">
      {(
        [
          ["movies", "Movies"],
          ["tv", "TV Shows"],
        ] as const
      ).map(([value, label]) => (
        <button
          key={value}
          role="tab"
          aria-selected={tab === value}
          onClick={() => setTab(value)}
          className={`rounded-pill border px-4 py-1.5 text-sm font-semibold ${
            tab === value
              ? "border-accent bg-accent-soft text-accent"
              : "border-line text-fg2 hover:bg-bg2"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );

  if (tab === "tv") {
    return (
      <div className="page-enter">
        <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
          Missing
        </h1>
        <p className="mb-4 mt-1 max-w-2xl text-sm text-fg2">
          A few shows you might want next. Deliberately a short list — a series is dozens of hours,
          so a handful you would genuinely start beats a page you never finish reading.
        </p>
        {tabs}
        <ShowSuggestions />
      </div>
    );
  }

  return (
    <div className="page-enter">
      {tabs}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
            Missing
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-fg2">
            Widely received theatrical films your Plex library doesn&rsquo;t have — blockbusters,
            cult classics, criterion-caliber picks, top-rated and award-winning titles.
            {total > 0 && (
              <span className="font-semibold text-fg"> {total.toLocaleString()} missing.</span>
            )}
            {requestedTotal > 0 && (
              <span className="text-fg3">
                {" "}
                {requestedTotal.toLocaleString()} already requested and on the way — hidden here
                until they land.
              </span>
            )}
          </p>
        </div>
        <button
          onClick={() => void refresh()}
          disabled={refreshing}
          className="gradient-fill shrink-0 rounded-pill px-4 py-1.5 text-sm font-bold shadow-glow disabled:opacity-60"
        >
          {refreshing ? "Refreshing catalog…" : "Refresh catalog"}
        </button>
      </div>
      {note && (
        <p className="mt-3 rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-fg2">
          {note}
        </p>
      )}

      <div className="mt-4">
        {loading ? (
          <div className="panel p-4" aria-busy="true">
            <span className="sr-only" role="status">
              Loading the missing list…
            </span>
            <div className="flex flex-wrap gap-3">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-[162px] w-[108px]" />
              ))}
            </div>
          </div>
        ) : items.length === 0 ? (
          <div className="panel">
            <EmptyState
              title="No catalog yet"
              hint="Refresh builds the canon from TMDB (top-rated + blockbusters) and the curated lists, then compares it against your Plex library."
              action={
                <button
                  onClick={() => void refresh()}
                  disabled={refreshing}
                  className="gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow disabled:opacity-60"
                >
                  {refreshing ? "Refreshing…" : "Build the catalog"}
                </button>
              }
            />
          </div>
        ) : (
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-3">
              <span className="text-xs text-fg3">
                Showing {visible.length.toLocaleString()} of {items.length.toLocaleString()}
              </span>
              {/* Requests what's on screen, not the whole canon — "request all" against
                  several hundred titles is never what someone means by one click. */}
              <RequestAllButton
                items={visible}
                label={`Request all ${visible.length} shown`}
                confirmFirst
                onDone={() => void load()}
              />
            </div>
            <div className="flex flex-wrap gap-3">
              {visible.map((m) => (
                <RequestCard
                  key={m.tmdb_id}
                  tmdbId={m.tmdb_id}
                  title={m.title}
                  year={m.year}
                  subtitle={m.sources.join(" · ")}
                  voteAverage={m.vote_average}
                />
              ))}
            </div>
            {items.length > FOLD && (
              <button
                onClick={() => setShowAll((v) => !v)}
                className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
              >
                {showAll ? "Show fewer" : `Show all (${items.length})`}
              </button>
            )}
            <p className="mt-3 text-xs text-fg3">
              The catalog itself lives in the backend — built deterministically from TMDB charts
              and the curated lists; the AI curator can propose, but every title passes the same
              gates before it counts.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
