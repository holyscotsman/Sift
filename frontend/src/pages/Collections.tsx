// Collections — incomplete sets you own part of, with one-click requests for
// the gaps. Requests go through Overseerr when it's configured, Radarr otherwise.

import { useEffect, useState } from "react";

import { CheckIcon } from "@/components/icons";
import { RequestAllButton, RequestButton } from "@/components/RequestCard";
import { EmptyState, Poster, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { CollectionGap } from "@/lib/types";

export function Collections() {
  const [gaps, setGaps] = useState<CollectionGap[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .missingCollections()
      .then((r) => setGaps(r.collections))
      .catch(() => setGaps([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="page-enter">
      <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
        Collections
      </h1>
      <p className="mt-1 text-sm text-fg2">
        Sets you own part of. Request the gaps — through Overseerr when it&rsquo;s connected,
        otherwise straight to Radarr.
      </p>

      <div className="mt-4">
        {loading ? (
          <div className="panel p-4" aria-busy="true">
            <span className="sr-only" role="status">
              Loading collections…
            </span>
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="mb-2 h-16" />
            ))}
          </div>
        ) : gaps.length === 0 ? (
          <div className="panel">
            <EmptyState
              title="No collection gaps"
              hint="Every collection you own part of is complete — or no collections were found yet."
            />
          </div>
        ) : (
          <div className="panel divide-y divide-line">
            {gaps.map((g) => (
              <div key={g.collection_id} className="p-4">
                <div className="mb-3 flex items-center gap-2">
                  <span className="font-display text-base font-bold">{g.name}</span>
                  <span className="text-sm text-fg3">
                    {g.owned_count}/{g.total_count} owned
                  </span>
                  <RequestAllButton items={g.members.filter((m) => !m.owned)} />
                </div>
                <div className="flex flex-wrap gap-3">
                  {g.members.map((m) => (
                    <div key={m.tmdb_id} className="w-[92px]">
                      <div
                        className="relative aspect-[2/3] overflow-hidden rounded-md"
                        style={m.owned ? undefined : { border: "1.5px dashed var(--line-2)" }}
                      >
                        <Poster
                          tmdbId={m.tmdb_id}
                          alt=""
                          label={m.title}
                          className={`h-full w-full ${m.owned ? "" : "opacity-40 grayscale"}`}
                        />
                        {m.owned ? (
                          <span
                            className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full"
                            style={{ background: "var(--keep)" }}
                          >
                            <CheckIcon size={11} className="text-[color:var(--accent-fg)]" />
                          </span>
                        ) : (
                          <span className="absolute inset-x-1 bottom-1 rounded-sm bg-black/50 py-0.5 text-center text-[10px] font-semibold text-white backdrop-blur">
                            missing
                          </span>
                        )}
                      </div>
                      <p className="mt-1 truncate text-[11px] text-fg3">
                        {m.title} {m.year ? `· ${m.year}` : ""}
                      </p>
                      {!m.owned && <RequestButton tmdbId={m.tmdb_id} title={m.title} />}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
