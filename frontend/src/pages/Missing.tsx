// Missing — one endless list of films worth owning that this library doesn't
// have.
//
// It reads the backend's canon and subtracts three things: what is in Plex, what
// has already been requested, and what has been set aside. The third is the one
// that makes it a queue rather than a wall — without it the same twenty titles
// greet you at the top forever, and the list is only useful if working through
// it visibly shortens it.
//
// Where the list comes from is deliberately not on screen. It is a
// recommendation, not a citation, and naming the file behind it would invite
// arguing with the file instead of deciding about the film.

import { useCallback, useEffect, useRef, useState } from "react";

import { RequestAllButton, RequestCard } from "@/components/RequestCard";
import { useToast } from "@/components/Toast";
import { EmptyState, Skeleton } from "@/components/ui";
import { ShowSuggestions } from "@/components/ShowSuggestions";
import { api } from "@/lib/api";
import type { SuggestionItem } from "@/lib/types";

const PAGE_SIZE = 60;

const TIER_LABEL: Record<number, string> = {
  1: "Essential",
  2: "Major",
  3: "Notable",
  4: "Well known",
};

const REASON_LABEL: Record<string, string> = {
  criterion: "Criterion",
  cult: "Cult",
  award: "Award",
  imdb_wr: "Consensus",
  canon_patch: "Curated",
  floor_override: "Curated",
};

function describe(item: SuggestionItem): string {
  const reasons = item.reasons.map((r) => REASON_LABEL[r] ?? r).filter(Boolean);
  const tier = TIER_LABEL[item.tier];
  return [tier, ...reasons].filter(Boolean).join(" · ");
}

export function Missing() {
  const [tab, setTab] = useState<"movies" | "tv">("movies");
  const [items, setItems] = useState<SuggestionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [requestedTotal, setRequestedTotal] = useState(0);
  const [ignoredTotal, setIgnoredTotal] = useState(0);
  const [tier, setTier] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  // A dropped page is not a dropped list: the titles already on screen are still
  // good, so this is reported at the bottom rather than replacing them.
  const [pageError, setPageError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const offsetRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const toastError = useToast();

  const fetchPage = useCallback(
    async (offset: number, replace: boolean) => {
      setLoading(true);
      try {
        const r = await api.suggestions({ tier, limit: PAGE_SIZE, offset });
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]));
        setTotal(r.total);
        setRequestedTotal(r.requested_total);
        setIgnoredTotal(r.ignored_total);
        // A short page is the end of the data. Trusting the total instead would
        // keep asking forever whenever a title is acted on mid-scroll.
        if (r.items.length < PAGE_SIZE) setDone(true);
        if (replace) setLoadError(null);
        setPageError(null);
      } catch (e: unknown) {
        const message =
          (e as { message?: string })?.message ||
          "Couldn't load the list. This is not the same as owning everything.";
        // Roll the offset back so a retry asks for the page that failed rather
        // than the one after it — otherwise those titles are gone for good with
        // nothing on screen to distinguish it from the end of the list.
        if (replace) setLoadError(message);
        else {
          offsetRef.current = Math.max(0, offset - PAGE_SIZE);
          setPageError(message);
        }
      } finally {
        setLoading(false);
      }
    },
    [tier],
  );

  useEffect(() => {
    offsetRef.current = 0;
    setItems([]);
    setDone(false);
    setPageError(null);
    void fetchPage(0, true);
  }, [fetchPage]);

  const loadMore = useCallback(() => {
    // `pageError` stops the observer re-firing into the same failure while the
    // sentinel stays on screen; clearing it is what the retry button does.
    if (loading || done || pageError || loadError) return;
    offsetRef.current += PAGE_SIZE;
    void fetchPage(offsetRef.current, false);
  }, [loading, done, pageError, loadError, fetchPage]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { rootMargin: "800px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  const ignore = useCallback(async (tmdbId: number, title: string) => {
    await api.ignoreTitle(tmdbId, title, "missing");
    setIgnoredTotal((n) => n + 1);
    setTotal((n) => Math.max(0, n - 1));
  }, []);

  const undoIgnore = useCallback(async (tmdbId: number) => {
    await api.unignoreTitle(tmdbId);
    setIgnoredTotal((n) => Math.max(0, n - 1));
    setTotal((n) => n + 1);
  }, []);

  async function refresh() {
    setRefreshing(true);
    setNote(null);
    try {
      const r = await api.canonRefresh();
      setNote(
        `Catalog refreshed — ${r.canon_written.toLocaleString()} titles in the catalog.`,
      );
      offsetRef.current = 0;
      setDone(false);
      await fetchPage(0, true);
    } catch {
      toastError("The catalog refresh failed — check the TMDB connection.");
    } finally {
      setRefreshing(false);
    }
  }

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

  const firstLoad = loading && items.length === 0;

  return (
    <div className="page-enter">
      {tabs}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
            Missing
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-fg2">
            Films worth owning that your Plex library doesn&rsquo;t have, strongest claim first.
            {total > 0 && (
              <span className="font-semibold text-fg"> {total.toLocaleString()} to go.</span>
            )}
            {requestedTotal > 0 && (
              <span className="text-fg3">
                {" "}
                {requestedTotal.toLocaleString()} already requested and on the way.
              </span>
            )}
            {ignoredTotal > 0 && (
              <span className="text-fg3"> {ignoredTotal.toLocaleString()} set aside.</span>
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

      <div className="mt-3 flex flex-wrap gap-1" role="group" aria-label="Filter by strength">
        {([null, 1, 2, 3, 4] as const).map((value) => (
          <button
            key={String(value)}
            aria-pressed={tier === value}
            onClick={() => setTier(value)}
            className={`rounded-pill border px-3 py-1 text-xs font-semibold ${
              tier === value
                ? "border-accent bg-accent-soft text-accent"
                : "border-line text-fg2 hover:bg-bg2"
            }`}
          >
            {value === null ? "Everything" : TIER_LABEL[value]}
          </button>
        ))}
      </div>

      {note && (
        <p className="mt-3 rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-fg2">
          {note}
        </p>
      )}

      <div className="mt-4">
        {firstLoad ? (
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
        ) : loadError ? (
          <div className="panel p-4 text-sm" style={{ color: "var(--junk)" }}>
            <p className="font-semibold">{loadError}</p>
            <button
              onClick={() => {
                setLoadError(null);
                offsetRef.current = 0;
                void fetchPage(0, true);
              }}
              className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
            >
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="panel">
            <EmptyState
              title="Nothing left on this list"
              hint="Either the catalog hasn't been built yet, or you own — or have decided about — everything in it. Refresh rebuilds the catalog and compares it against your Plex library again."
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
                Showing {items.length.toLocaleString()} of {total.toLocaleString()}
              </span>
              {/* Requests what's on screen, not the whole list — "request all"
                  against twenty thousand titles is never what one click means. */}
              <RequestAllButton
                items={items}
                label={`Request all ${items.length} shown`}
                confirmFirst
              />
            </div>
            <div className="flex flex-wrap gap-3">
              {items.map((m) => (
                <RequestCard
                  key={m.tmdb_id}
                  tmdbId={m.tmdb_id}
                  title={m.title}
                  year={m.year}
                  subtitle={describe(m)}
                  voteAverage={m.rating}
                  onIgnore={ignore}
                  onUndoIgnore={undoIgnore}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Infinite-scroll sentinel + status. */}
      <div ref={sentinelRef} className="h-6" />
      {!firstLoad && loading && items.length > 0 && (
        <p className="py-4 text-center text-sm text-fg3">Loading more…</p>
      )}
      {pageError && (
        <div className="py-4 text-center text-sm" style={{ color: "var(--junk)" }}>
          <p className="font-semibold">{pageError}</p>
          <button
            onClick={() => {
              setPageError(null);
              offsetRef.current += PAGE_SIZE;
              void fetchPage(offsetRef.current, false);
            }}
            className="mt-2 rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
          >
            Load the rest
          </button>
        </div>
      )}
      {done && items.length > 0 && !pageError && (
        <p className="py-4 text-center text-sm text-fg3">That&rsquo;s everything.</p>
      )}
    </div>
  );
}
