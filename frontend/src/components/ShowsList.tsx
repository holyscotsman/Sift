// The TV half of the Library.
//
// Deliberately not a mirror of the film list. The film list exists to answer
// "should this be here"; this one does not, because shows are never scored for
// removal — a series is forty hours rather than two, and whether it *deserves*
// the space is not a question Sift has been asked to have an opinion about.
//
// So the columns are the ones a person actually wants when looking at a shelf of
// television: how much of it there is, what it costs, what quality it is in, and
// whether you ever watch it.

import { useEffect, useMemo, useState } from "react";

import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtSize as fmtBytes } from "@/lib/format";
import type { ShowSummary } from "@/lib/types";

function fmtWatched(show: ShowSummary): string {
  if (!show.plays) return "never";
  if (!show.last_played_at) return `${show.plays} plays`;
  const days = Math.round((Date.now() - Date.parse(show.last_played_at)) / 86_400_000);
  if (days <= 1) return "today";
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.round(days / 30)} months ago`;
  return `${(days / 365).toFixed(1)} years ago`;
}

const SORTS = [
  { value: "title", label: "Title" },
  { value: "year", label: "Year" },
  { value: "last_played_at", label: "Last watched" },
] as const;

export function ShowsList({ query }: { query: string }) {
  const [shows, setShows] = useState<ShowSummary[] | null>(null);
  const [sections, setSections] = useState<string[]>([]);
  const [section, setSection] = useState<string>("");
  const [sort, setSort] = useState<string>("title");
  const [total, setTotal] = useState(0);
  const [totalSize, setTotalSize] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.showSections().then(setSections).catch(() => setSections([]));
  }, []);

  useEffect(() => {
    let live = true;
    setShows(null);
    api
      .shows({ q: query, section, sort, order: sort === "last_played_at" ? "desc" : "asc" })
      .then((r) => {
        if (!live) return;
        setShows(r.items);
        setTotal(r.total);
        setTotalSize(r.total_size);
      })
      .catch((e) => live && setError((e as { message?: string })?.message || "Couldn't load shows."));
    return () => {
      live = false;
    };
  }, [query, section, sort]);

  const summary = useMemo(() => {
    if (!shows) return "Loading…";
    const episodes = shows.reduce((n, s) => n + s.episode_count, 0);
    return `${total.toLocaleString()} shows · ${episodes.toLocaleString()} episodes · ${fmtBytes(totalSize)}`;
  }, [shows, total, totalSize]);

  if (error) {
    return (
      <div className="panel p-4 text-sm" style={{ color: "var(--junk)" }}>
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-fg2">{summary}</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="rounded-md border border-line bg-bg2 px-2 py-1.5 text-sm text-fg"
            aria-label="Library"
          >
            <option value="">All libraries</option>
            {sections.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-md border border-line bg-bg2 px-2 py-1.5 text-sm text-fg"
            aria-label="Sort"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!shows ? (
        <div className="panel flex flex-col gap-2 p-4" aria-busy="true">
          <span className="sr-only" role="status">
            Loading shows
          </span>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : shows.length === 0 ? (
        <EmptyState
          title="No shows yet"
          hint="Connect Sonarr in Settings and run a scan. Every Plex show library counts — Cartoons, Anime, Game Shows and the rest."
        />
      ) : (
        <div className="panel divide-y divide-line">
          {shows.map((show) => (
            <div key={show.tvdb_id} className="flex flex-wrap items-center gap-3 p-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{show.title}</span>
                  {show.year ? <span className="text-xs text-fg3">{show.year}</span> : null}
                  {show.resolution ? <Pill>{show.resolution}</Pill> : null}
                  {show.library_section ? (
                    <span className="text-xs text-fg3">{show.library_section}</span>
                  ) : null}
                </div>
                <p className="mt-0.5 text-xs text-fg2">
                  {show.season_count} season{show.season_count === 1 ? "" : "s"} ·{" "}
                  {show.episode_count} episode{show.episode_count === 1 ? "" : "s"} · watched{" "}
                  {fmtWatched(show)}
                </p>
              </div>
              <span className="shrink-0 text-sm font-bold tabular-nums">
                {fmtBytes(show.total_size)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
