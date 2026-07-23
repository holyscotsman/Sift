// Library — grid/table over the real /api/movies with continuous (infinite)
// scrolling. Pages are fetched and appended as a sentinel near the bottom scrolls
// into view. Deep-links from global search via ?q=.

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router-dom";

import { GridIcon, TableIcon } from "@/components/icons";
import { api, getToken } from "@/lib/api";
import type { MovieQuery } from "@/lib/api";
import { EmptyState, Pill, Poster, Skeleton } from "@/components/ui";
import { useDrawer } from "@/lib/drawer";
import { useScan } from "@/lib/scan";
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

const ALPHABET = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];

function fmtBytes(bytes: number): string {
  return bytes >= 1e12 ? `${(bytes / 1e12).toFixed(2)} TB` : `${(bytes / 1e9).toFixed(1)} GB`;
}

export function Library() {
  const [params, setParams] = useSearchParams();
  const { start: startScan } = useScan();
  const q = params.get("q") ?? "";
  // View and sort survive navigation — read once, written on change.
  const [view, setViewState] = useState<View>(() =>
    localStorage.getItem("sift.library.view") === "table" ? "table" : "grid",
  );
  const setView = (v: View) => {
    localStorage.setItem("sift.library.view", v);
    setViewState(v);
  };
  // Seed the quick filter from a deep-link (e.g. Dashboard → ?filter=upgrades).
  const seeded = params.get("filter") as Quick | null;
  const [quick, setQuick] = useState<Quick>(
    seeded && QUICK_ORDER.includes(seeded) ? seeded : "plex",
  );
  const [sort, setSortState] = useState(() => {
    const stored = localStorage.getItem("sift.library.sort");
    return stored && ["title", "year", "added_at", "file_size"].includes(stored)
      ? stored
      : "title";
  });
  const setSort = (s: string) => {
    localStorage.setItem("sift.library.sort", s);
    setSortState(s);
  };
  // Plex sections for the section filter; the control hides when there's ≤1.
  const [sections, setSections] = useState<string[]>([]);
  const [section, setSection] = useState("");
  // null = the field's natural direction (title A→Z, everything else newest/biggest
  // first). Clicking a table header on the active field flips it.
  const [order, setOrder] = useState<"asc" | "desc" | null>(null);
  // A–Z rail jump (only meaningful when ordered by title). null = no letter filter.
  const [letter, setLetter] = useState<string | null>(null);
  const pageSize = view === "grid" ? 36 : 60;

  const [items, setItems] = useState<Movie[]>([]);
  const [total, setTotal] = useState(0);
  const [totalSize, setTotalSize] = useState(0);
  const [loading, setLoading] = useState(true);
  const [done, setDone] = useState(false);
  const pageRef = useRef(1);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // A stable key over everything that changes the result set. Changing it resets
  // the accumulated list and reloads from page 1.
  // Letter jump only applies when sorted by title; ignore it otherwise.
  const activeLetter = sort === "title" ? letter : null;
  const effectiveOrder: "asc" | "desc" = order ?? (sort === "title" ? "asc" : "desc");

  // Header click: same field flips direction, a new field starts at its natural one.
  const sortBy = useCallback(
    (field: string) => {
      if (field === sort) {
        setOrder(effectiveOrder === "asc" ? "desc" : "asc");
      } else {
        setSort(field);
        setOrder(null);
      }
    },
    [sort, effectiveOrder],
  );

  const filterKey = useMemo(
    () => JSON.stringify({ q, quick, sort, effectiveOrder, pageSize, activeLetter, section }),
    [q, quick, sort, effectiveOrder, pageSize, activeLetter, section],
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
      starts_with: activeLetter ?? undefined,
      section: section || undefined,
      sort,
      order: effectiveOrder,
      page,
      page_size: pageSize,
    }),
    [q, quick, sort, effectiveOrder, pageSize, activeLetter, section],
  );

  useEffect(() => {
    api
      .movieSections()
      .then(setSections)
      .catch(() => setSections([]));
  }, []);

  const fetchPage = useCallback(
    async (page: number, replace: boolean) => {
      setLoading(true);
      try {
        const res = await api.movies(buildQuery(page));
        // The server only computes totals for page 1 — appended pages return
        // zeros there, so keep the page-1 values while scrolling.
        if (replace) {
          setTotal(res.total);
          setTotalSize(res.total_size ?? 0);
        }
        setItems((prev) => (replace ? res.items : [...prev, ...res.items]));
        setDone(
          res.items.length < pageSize || (replace && res.total <= page * pageSize),
        );
      } finally {
        setLoading(false);
      }
    },
    [buildQuery, pageSize],
  );

  // CSV download of exactly the visible set — same filters/sort, token in the
  // query (a download link can't send auth headers, mirroring the poster route).
  const exportHref = useMemo(() => {
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(buildQuery(1))) {
      if (k === "page" || k === "page_size" || v === undefined || v === null) continue;
      usp.set(k, String(v));
    }
    const token = getToken();
    if (token) usp.set("token", token);
    return `/api/movies.csv?${usp.toString()}`;
  }, [buildQuery]);

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
              : `${QUICK_LABELS[quick]} · ${items.length.toLocaleString()} of ${total.toLocaleString()}${
                  totalSize > 0 ? ` · ${fmtBytes(totalSize)}` : ""
                }`}
            {q && <span className="text-fg3"> · filtered by “{q}”</span>}
            {activeLetter && (
              <button
                onClick={() => setLetter(null)}
                className="ml-1 text-accent hover:underline"
              >
                · jumped to “{activeLetter}” (clear)
              </button>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a
            href={exportHref}
            download
            className="rounded-pill border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
          >
            Export CSV
          </a>
          <div className="flex items-center gap-1 rounded-pill border border-line p-0.5">
            <ViewBtn active={view === "grid"} onClick={() => setView("grid")} label="Grid">
              <GridIcon size={15} />
            </ViewBtn>
            <ViewBtn active={view === "table"} onClick={() => setView("table")} label="Table">
              <TableIcon size={15} />
            </ViewBtn>
          </div>
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
          {sections.length > 1 && (
            <>
              <label className="text-fg3">Section</label>
              <select
                value={section}
                onChange={(e) => setSection(e.target.value)}
                className="rounded-md border border-line bg-panel px-2 py-1 text-sm text-fg"
              >
                <option value="">All</option>
                {sections.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </>
          )}
          <label className="text-fg3">Sort</label>
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              setOrder(null);
            }}
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
        <div aria-busy="true">
          <span className="sr-only" role="status">
            Loading library…
          </span>
          <LoadingState view={view} />
        </div>
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="No movies match these filters"
            hint={q ? "Try a different search or clear filters." : "Run a scan to populate the library."}
            action={
              q ? (
                <button
                  onClick={() => setParams({})}
                  className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
                >
                  Clear filters
                </button>
              ) : (
                <button
                  onClick={() => void startScan()}
                  className="gradient-fill rounded-md px-4 py-2 text-sm font-bold shadow-glow"
                >
                  Run scan
                </button>
              )
            }
          />
        </div>
      ) : view === "grid" ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(158px, 1fr))" }}>
          {items.map((m) => (
            <GridTile key={m.tmdb_id} movie={m} />
          ))}
        </div>
      ) : (
        <TableView items={items} sort={sort} order={effectiveOrder} onSort={sortBy} />
      )}

      {/* A–Z rail: jump straight to a letter when ordered by title. Portaled to
          <body> — the page container animates with a transform, and a transformed
          ancestor turns position:fixed into scroll-along absolute, which made the
          rail drift away as you scrolled. */}
      {sort === "title" &&
        !q &&
        createPortal(
          <nav
            aria-label="Jump to letter"
            className="fixed right-1 top-1/2 z-30 hidden -translate-y-1/2 flex-col items-center gap-px rounded-pill border border-line bg-panel px-0.5 py-1.5 shadow-md md:flex"
          >
            {ALPHABET.map((L) => (
              <button
                key={L}
                onClick={() => setLetter(L === activeLetter ? null : L)}
                aria-pressed={L === activeLetter}
                className={`h-[15px] w-4 rounded-pill text-[9px] font-bold leading-[15px] transition-colors ${
                  L === activeLetter ? "bg-accent text-accent-fg" : "text-fg3 hover:text-accent"
                }`}
              >
                {L}
              </button>
            ))}
          </nav>,
          document.body,
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

// Memoized: infinite scroll appends rebuild the items array, but existing Movie
// objects keep their identity — so already-rendered tiles skip re-rendering.
const GridTile = memo(function GridTile({ movie }: { movie: Movie }) {
  const { open } = useDrawer();
  return (
    <button className="group text-left" onClick={() => open(movie.tmdb_id)}>
      <div className="relative aspect-[2/3] overflow-hidden rounded-md">
        <Poster tmdbId={movie.tmdb_id} alt="" label={movie.title} className="h-full w-full" />
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
});

function SortableTh({
  field,
  sort,
  order,
  onSort,
  children,
  className = "",
}: {
  field: string;
  sort: string;
  order: "asc" | "desc";
  onSort: (field: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  const active = sort === field;
  return (
    <th
      className={`py-3 font-semibold ${className}`}
      aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
    >
      <button
        onClick={() => onSort(field)}
        className={`inline-flex items-center gap-1 uppercase tracking-wide hover:text-fg ${
          active ? "text-accent" : ""
        }`}
      >
        {children}
        {active && <span aria-hidden>{order === "asc" ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}

function TableView({
  items,
  sort,
  order,
  onSort,
}: {
  items: Movie[];
  sort: string;
  order: "asc" | "desc";
  onSort: (field: string) => void;
}) {
  const { open } = useDrawer();
  return (
    <div className="panel overflow-x-auto">
      <table className="movie-table w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-fg3">
            <SortableTh field="title" sort={sort} order={order} onSort={onSort} className="px-4">
              Title
            </SortableTh>
            <SortableTh
              field="year"
              sort={sort}
              order={order}
              onSort={onSort}
              className="hidden px-3 md:table-cell"
            >
              Year
            </SortableTh>
            <th className="px-3 py-3 font-semibold">Library</th>
            <th className="hidden px-3 py-3 font-semibold md:table-cell">Quality</th>
            <SortableTh
              field="file_size"
              sort={sort}
              order={order}
              onSort={onSort}
              className="hidden px-3 md:table-cell"
            >
              Size
            </SortableTh>
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
              <td className="flex items-center gap-3 px-4">
                <Poster tmdbId={m.tmdb_id} alt="" className="h-9 w-6 shrink-0 rounded-sm" />
                <span className="font-medium text-fg">{m.title}</span>
              </td>
              <td className="hidden px-3 text-fg2 md:table-cell">{m.year ?? "—"}</td>
              <td className="px-3 text-fg2">{m.library_section ?? "—"}</td>
              <td className="hidden px-3 md:table-cell">
                <span className="flex items-center gap-1.5">
                  {m.quality ? <Pill>{m.quality}</Pill> : <span className="text-fg3">—</span>}
                  {m.cutoff_unmet && (
                    <Pill tone="borderline" title="Below Radarr quality cutoff — upgrade wanted">
                      ↑ upgrade
                    </Pill>
                  )}
                </span>
              </td>
              <td className="hidden px-3 text-fg2 md:table-cell">
                {m.file_size ? `${(m.file_size / 1e9).toFixed(1)} GB` : "—"}
              </td>
              <td className="px-3">
                {m.in_plex ? <Pill tone="keep">Yes</Pill> : <span className="text-fg3">—</span>}
              </td>
              <td className="hidden px-3 md:table-cell">
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
