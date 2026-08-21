// A handful of shows you might want next.
//
// Short on purpose. Twenty-four film suggestions is a browse; twenty-four show
// suggestions is a second job, and a list nobody finishes reading is worse than
// one half its length.
//
// Each card says which of your shows led there, so a suggestion can be argued
// with rather than just accepted or ignored.

import { useEffect, useState } from "react";

import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ShowSuggestion } from "@/lib/types";

export function ShowSuggestions() {
  const [items, setItems] = useState<ShowSuggestion[] | null>(null);
  const [detail, setDetail] = useState("");

  useEffect(() => {
    let live = true;
    api
      .showSuggestions()
      .then((r) => {
        if (!live) return;
        setItems(r.items);
        setDetail(r.detail);
      })
      .catch((e: unknown) =>
        live && setDetail((e as { message?: string })?.message || "Something went wrong."),
      );
    return () => {
      live = false;
    };
  }, []);

  if (!items) {
    // `detail` is only set here by the catch, and it has to have somewhere to go:
    // without this branch a failed request left the skeleton shimmering forever
    // and the reason was written to state nothing rendered.
    if (detail) return <EmptyState title="Couldn't load suggestions" hint={detail} />;
    return (
      <div className="panel flex flex-col gap-2 p-4" aria-busy="true">
        <span className="sr-only" role="status">
          Looking for shows
        </span>
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  if (items.length === 0) {
    return <EmptyState title="Nothing to suggest yet" hint={detail} />;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="panel divide-y divide-line">
        {items.map((show) => (
          <div key={show.tmdb_id} className="flex flex-wrap items-start gap-3 p-3.5">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate text-sm font-semibold">{show.title}</span>
                {show.year ? <span className="text-xs text-fg3">{show.year}</span> : null}
                {show.vote_average ? <Pill>{show.vote_average.toFixed(1)}</Pill> : null}
              </div>
              {show.because_of.length > 0 ? (
                <p className="mt-0.5 text-xs text-fg2">
                  Because you watched {show.because_of.join(", ")}
                </p>
              ) : null}
              {show.overview ? (
                <p className="mt-1 line-clamp-2 text-xs text-fg3">{show.overview}</p>
              ) : null}
            </div>
            <a
              href={`https://www.themoviedb.org/tv/${show.tmdb_id}`}
              target="_blank"
              rel="noreferrer"
              className="shrink-0 rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
            >
              Look it up
            </a>
          </div>
        ))}
      </div>
      <p className="text-xs text-fg3">
        Suggestions only — nothing is requested or added from here.
      </p>
    </div>
  );
}
