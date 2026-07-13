// Library — grid/table over the real /api/movies with continuous (infinite)
// scrolling. Pages are fetched and appended as a sentinel near the bottom scrolls
// into view. Deep-links from global search via ?q=.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { GridIcon, TableIcon } from "@/components/icons";
import { api } from "@/lib/api";
import type { MovieQuery } from "@/lib/api";
import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { useDrawer } from "@/lib/drawer";
import type { Movie } from "@/lib/types";

type View = "grid" | "table";
type Quick = "plex" | "all" | "monitored" | "kids" | "upgrades";

const QUICK_ORDER: Quick[] = ["plex", "all", "monitored", "kids", "upgrades"];

const QUICK_LABELS: Record<Quick, string> = {
  plex: "In Plex",
  all: "All",
  monitored: "Monitored",
  kids: "Kids",
  upgrades: "Below cutoff",
};

function posterGradient(id: number): string {
  const hue = (id * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 44% 32%), hsl(${(hue + 38) % 360} 40% 15%))`;
}

export function Library() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [view, setView] = useState<View>("grid");
  // Seed the quick filter from a deep-link (e.g. Dashboard → ?filter=upgrades).
  const seeded = params.get("filter") as Quick | null;
  const [quick, setQuick] = useState<Quick>(
    seeded && QUICK_ORDER.includes(seeded) ? seeded : "plex",
  );
  const [sort, setSort] = useState("title");
  const pageSize = view === "grid" ? 36 : 60;

  const [items, setItems] = useState<Movie[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  const pageRef = useRef(1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // A stable key over everything that changes the result set. Changing it resets
  // the accumulated list and reloads from page 1.
  const filterKey = useMemo(
    () => JSON.stringify({ q, quick, sort, pageSize }),
    [q, quick, sort, pageSize],
  );

  const buildQuery = useCallback(
    (page: number): MovieQuery => ({
      q: q || undefined,
      // "Below cutoff" is a library view (Plex is the source of truth) narrowed to
      // titles Radarr says are under the quality cutoff.
      in_plex: quick === "plex" || quick === "upgrades" ? true : undefined,
      monitored: quick === "monitored" ? true : undefined,
      is_kids: quick === "kids" ? true : undefined,
      cutoff_unmet: quick === "upgrades" ? true : undefined,
      sort,
      order: sort === "title" ? "asc" : "desc",
      page,
      page_size: pageSize,
    }),
    [q, quick, sort, pageSize],
  );

  const fetchPage = useCallback(
    async (page: number, replace: boolean) => {
      setLoading(true);
      try {
        const res = await api.movies(buildQuery(page));
        setTotal(res.total);
        setItems((prev) => (replace ? res.items : [...prev, ...res.items]));
        setDone(page * pageSize >= res.total || res.items.length === 0);
      } finally {
        setLoading(false);
      }
    },
    [buildQuery, pageSize],
  );

  // Reset + load page 1 whenever the filters change.
  useEffect(() => {
    pageRef.current = 1;
    setItems([]);
    setTotal(0);
    setDone(false);
    void fetchPage(1, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const loadMore = useCallback(() => {
    if (loading || done) return;
    pageRef.current += 1;
    void fetchPage(pageRef.current, false);
  }, [loading, done, fetchPage]);

  // Observe a sentinel near the bottom; fetch the next page as it approaches.
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

  const firstLoad = loading && items.length === 0;

  return (
    <div className="page-enter">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
            Library
          </h1>
          <p className="mt-1 text-sm text-fg2">
            {firstLoad
              ? "Loading…"
              : `${QUICK_LABELS[quick]} · ${items.length.toLocaleString()} of ${total.toLocaleString()}`}
            {q && <span className="text-fg3"> · filtered by “{q}”</span>}
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-pill border border-line p-0.5">
          <ViewBtn active={view === "grid"} onClick={() => setView("grid")} label="Grid">
            <GridIcon size={15} />
          </ViewBtn>
          <ViewBtn active={view === "table"} onClick={() => setView("table")} label="Table">
            <TableIcon size={15} />
          </ViewBtn>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {QUICK_ORDER.map((k) => (
          <button
            key={k}
            onClick={() => setQuick(k)}
            className={`rounded-pill px-3 py-1 text-[13px] font-semibold ${
              quick === k ? "bg-accent-soft text-accent" : "text-fg2 hover:bg-bg2"
            }`}
          >
            {QUICK_LABELS[k]}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-sm">
          <label className="text-fg3">Sort</label>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-md border border-line bg-panel px-2 py-1 text-sm text-fg"
          >
            <option value="title">Title</option>
            <option value="year">Year</option>
            <option value="added_at">Added</option>
            <option value="file_size">Size</option>
          </select>
          {q && (
            <button
              onClick={() => setParams({})}
              className="rounded-md border border-line px-2 py-1 text-xs text-fg2 hover:bg-bg2"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {firstLoad ? (
        <LoadingState view={view} />
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="No movies match these filters"
            hint={q ? "Try a different search or clear filters." : "Run a scan to populate the library."}
          />
        </div>
      ) : view === "grid" ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(158px, 1fr))" }}>
          {items.map((m) => (
            <GridTile key={m.tmdb_id} movie={m} />
          ))}
        </div>
      ) : (
        <TableView items={items} />
      )}

      {/* Infinite-scroll sentinel + status. */}
      <div ref={sentinelRef} className="h-6" />
      {!firstLoad && loading && items.length > 0 && (
        <p className="py-4 text-center text-sm text-fg3">Loading more…</p>
      )}
      {done && items.length > 0 && (
        <p className="py-6 text-center text-xs text-fg3">
          That’s everything · {total.toLocaleString()} titles
        </p>
      )}
    </div>
  );
}

function ViewBtn({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={`grid h-7 w-8 place-items-center rounded-pill ${
        active ? "bg-accent-soft text-accent" : "text-fg3 hover:text-fg"
      }`}
    >
      {children}
    </button>
  );
}

function GridTile({ movie }: { movie: Movie }) {
  const { open } = useDrawer();
  return (
    <button className="group text-left" onClick={() => open(movie.tmdb_id)}>
      <div
        className="relative aspect-[2/3] overflow-hidden rounded-md"
        style={movie.poster_url ? undefined : { background: posterGradient(movie.tmdb_id) }}
      >
        {movie.poster_url && (
          <img src={movie.poster_url} alt="" className="h-full w-full object-cover" loading="lazy" />
        )}
        {movie.quality && (
          <span className="absolute left-1.5 top-1.5 rounded-sm bg-black/50 px-1.5 py-0.5 text-[10px] font-semibold text-white backdrop-blur">
            {movie.quality}
          </span>
        )}
        {movie.monitored && (
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-pill bg-accent" title="Monitored" />
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2">
          <p className="truncate text-[13px] font-semibold text-white">{movie.title}</p>
        </div>
      </div>
      <p className="mt-1.5 truncate text-xs text-fg3">
        {movie.year ?? "—"} · {movie.library_section ?? "Unsorted"}
      </p>
    </button>
  );
}

function TableView({ items }: { items: Movie[] }) {
  const { open } = useDrawer();
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-fg3">
            <th className="px-4 py-3 font-semibold">Title</th>
            <th className="hidden px-3 py-3 font-semibold md:table-cell">Year</th>
            <th className="px-3 py-3 font-semibold">Library</th>
            <th className="hidden px-3 py-3 font-semibold md:table-cell">Quality</th>
            <th className="px-3 py-3 font-semibold">In Plex</th>
            <th className="hidden px-3 py-3 font-semibold md:table-cell">Monitored</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr
              key={m.tmdb_id}
              onClick={() => open(m.tmdb_id)}
              className="cursor-pointer border-b border-line/60 hover:bg-bg2"
            >
              <td className="flex items-center gap-3 px-4 py-2.5">
                <span className="h-9 w-6 shrink-0 rounded-sm" style={{ background: posterGradient(m.tmdb_id) }} />
                <span className="font-medium text-fg">{m.title}</span>
              </td>
              <td className="hidden px-3 py-2.5 text-fg2 md:table-cell">{m.year ?? "—"}</td>
              <td className="px-3 py-2.5 text-fg2">{m.library_section ?? "—"}</td>
              <td className="hidden px-3 py-2.5 md:table-cell">
                <span className="flex items-center gap-1.5">
                  {m.quality ? <Pill>{m.quality}</Pill> : <span className="text-fg3">—</span>}
                  {m.cutoff_unmet && (
                    <Pill tone="borderline" title="Below Radarr quality cutoff — upgrade wanted">
                      ↑ upgrade
                    </Pill>
                  )}
                </span>
              </td>
              <td className="px-3 py-2.5">
                {m.in_plex ? <Pill tone="keep">Yes</Pill> : <span className="text-fg3">—</span>}
              </td>
              <td className="hidden px-3 py-2.5 md:table-cell">
                {m.monitored ? <Pill tone="accent">Yes</Pill> : <span className="text-fg3">No</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LoadingState({ view }: { view: View }) {
  if (view === "grid") {
    return (
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(158px, 1fr))" }}>
        {Array.from({ length: 12 }).map((_, i) => (
          <Skeleton key={i} className="aspect-[2/3]" />
        ))}
      </div>
    );
  }
  return (
    <div className="panel p-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="mb-2 h-10" />
      ))}
    </div>
  );
}
