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
import { SetAsideList } from "@/components/SetAsideList";
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

// What the film *is*: the facts, for deciding whether you want it.
//
// The reasons used to be raw pillar tags (`cult`, `imdb_wr`) mapped to single
// words, which told you the film was "Consensus" and nothing else. They are
// sentences now, counted from your own library, so they get their own line
// rather than being crushed into this one.
// The one reason worth the space on a 108px card: the most specific one.
//
// The server returns them tier-first, which is the right order for a list but the
// wrong one for a card — "Widely regarded as essential" is already in the
// subtitle as its tier label, and repeating it in the accent colour says nothing
// new. What earns the line is the reason drawn from the owner's own shelf, which
// is also the only one they can check.
//
// Every field access here is defensive, and not out of politeness to the type
// checker: the type is a promise about the *shape we asked for*, and a deploy
// serves a new page against the old API for as long as it takes the backend to
// roll. A missing array crashed the whole Missing page rather than rendering one
// card without a director, which is the wrong trade by a wide margin.
function personalReason(item: SuggestionItem): string | undefined {
  const reasons = item.reasons ?? [];
  return (
    reasons.find((r) => r.startsWith("You own")) ??
    reasons.find((r) => r.includes("of your library")) ??
    // Nothing personal to say about this one. Naming the director is still worth
    // more than silence — it is the fact people recognise a film by — and it is
    // the only place the director appears now that the caption carries genre and
    // runtime instead.
    ((item.directors ?? [])[0] ? `Directed by ${(item.directors ?? [])[0]}` : undefined)
  );
}

// Two facts, because two is what fits.
//
// This line lives on a 108px card and truncates with an ellipsis. It used to
// carry four — tier, director, genres, runtime — which in a real browser rendered
// as "Essential · Joel Coe…" on every single card: the tier, half a name, and
// nothing else. Every fact after the first was invisible, including the two this
// line was widened to show. No unit test could see that; the string was composed
// correctly and then clipped by CSS.
//
// So the two that survive are the two the other lines do not already say. The
// title line carries the year. The reason line names the director whenever the
// director is *why* this film is here — which is most of the time, and far more
// usefully than a bare name would. Tier is a filter chip at the top of the page
// and the sort order of the list itself.
//
// That leaves genre and runtime: what kind of film, and how long an evening.
function describe(item: SuggestionItem): string {
  const runtime = item.runtime ? `${item.runtime} min` : null;
  // One genre. Two fitted in a mock-up and not in a browser: "Comedy, Drama ·
  // 116 min" is twenty-three characters where the card holds about twenty, so
  // the runtime clipped off every card that had two genres. Measured by asking
  // the rendered page which lines had scrollWidth past clientWidth, rather than
  // by counting characters and hoping.
  const genres = (item.genres ?? [])[0] || null;
  const line = [genres, runtime].filter(Boolean).join(" · ");
  // With no metadata at all there is still the tier to say, rather than an empty
  // line where a fact should be.
  return line || TIER_LABEL[item.tier] || "";
}

export function Missing() {
  const [tab, setTab] = useState<"movies" | "tv" | "aside">("movies");
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
  // Bumped when something outside this tab changes what belongs on the list —
  // bringing a film back from Set aside. Switching tabs does not remount this
  // component, so clearing `items` without a trigger would leave the Movies tab
  // permanently empty rather than reloading it.
  const [reloadKey, setReloadKey] = useState(0);
  const offsetRef = useRef(0);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const toastError = useToast();

  const fetchPage = useCallback(
    async (offset: number, replace: boolean) => {
      setLoading(true);
      try {
        const r = await api.suggestions({ tier, limit: PAGE_SIZE, offset });
        setItems((prev) => (replace ? r.items : [...prev, ...r.items]));
        // `null` is "not measured on this request", not zero. The server only
        // counts on the first page of a list, so overwriting blindly would flip
        // the header to nothing the moment anyone scrolled.
        if (r.total != null) setTotal(r.total);
        if (r.requested_total != null) setRequestedTotal(r.requested_total);
        if (r.ignored_total != null) setIgnoredTotal(r.ignored_total);
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
  }, [fetchPage, reloadKey]);

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

  // Find more films. TMDB discovery first, then whichever AI providers are
  // connected — both extending the same list rather than opening another one.
  async function findMore() {
    setRefreshing(true);
    setNote(null);
    try {
      const r = await api.topup();
      setNote(
        !r.ran
          ? (r.note ?? "Nothing to do right now.")
          : r.added > 0
            ? `Found ${r.added.toLocaleString()} more — ${r.remaining.toLocaleString()} on the list.`
            : "Nothing new this time. Try again to search further back.",
      );
      offsetRef.current = 0;
      setDone(false);
      await fetchPage(0, true);
    } catch {
      toastError("Couldn't look for more films — check the TMDB connection.");
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
          ["aside", "Set aside"],
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

  if (tab === "aside") {
    return (
      <div className="page-enter">
        <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
          Missing
        </h1>
        <p className="mb-4 mt-1 max-w-2xl text-sm text-fg2">
          Films you have passed on. They are never suggested again — by the built-in list, by
          TMDB, or by any AI you have connected — and this is the only place they appear.
        </p>
        {tabs}
        {/* A restored film rejoins the list at its usual rank, so the Movies tab's
            page and its counts are both one out. Bumping the key reloads it. */}
        <SetAsideList onRestored={() => setReloadKey((n) => n + 1)} />
      </div>
    );
  }

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
          onClick={() => void findMore()}
          disabled={refreshing}
          className="gradient-fill shrink-0 rounded-pill px-4 py-1.5 text-sm font-bold shadow-glow disabled:opacity-60"
        >
          {refreshing ? "Looking…" : "Find more"}
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
              hint="Either you own — or have decided about — everything on the list, or a scan hasn't run yet. Finding more asks TMDB, and any AI you have connected, for films past the ones Sift ships with."
              action={
                <button
                  onClick={() => void findMore()}
                  disabled={refreshing}
                  className="gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow disabled:opacity-60"
                >
                  {refreshing ? "Looking…" : "Find more films"}
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
              {/* Capped inside the component. This list is endless, so "what is on
                  screen" grows with every scroll and is not a bound at all. */}
              <RequestAllButton items={items} confirmFirst />
            </div>
            <div className="flex flex-wrap gap-3">
              {items.map((m) => (
                <RequestCard
                  key={m.tmdb_id}
                  tmdbId={m.tmdb_id}
                  title={m.title}
                  year={m.year}
                  subtitle={describe(m)}
                  reason={personalReason(m)}
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
