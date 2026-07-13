// Missing — collection gaps (deterministic) + taste recommendations (AI, next).

import { useEffect, useState } from "react";

import { CheckIcon, SparkleIcon } from "@/components/icons";
import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { CollectionGap } from "@/lib/types";

function posterGradient(id: number): string {
  const hue = (id * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 44% 32%), hsl(${(hue + 38) % 360} 40% 15%))`;
}

export function Missing() {
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
    <div className="page-enter flex flex-col gap-5">
      <div>
        <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
          Missing
        </h1>
        <p className="mt-1 text-sm text-fg2">Gaps in collections you already own part of.</p>
      </div>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="eyebrow">Collection gaps</span>
          <Pill tone="accent">Deterministic</Pill>
        </div>
        {loading ? (
          <div className="panel p-4">
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
                </div>
                <div className="flex flex-wrap gap-3">
                  {g.members.map((m) => (
                    <div key={m.tmdb_id} className="w-[92px]">
                      <div
                        className="relative aspect-[2/3] rounded-md"
                        style={
                          m.owned
                            ? { background: posterGradient(m.tmdb_id) }
                            : { border: "1.5px dashed var(--line-2)" }
                        }
                      >
                        {m.owned ? (
                          <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full" style={{ background: "var(--keep)" }}>
                            <CheckIcon size={11} className="text-[color:var(--accent-fg)]" />
                          </span>
                        ) : (
                          <span className="absolute inset-x-1 bottom-1 text-center text-[10px] text-fg3">
                            missing
                          </span>
                        )}
                      </div>
                      <p className="mt-1 truncate text-[11px] text-fg3">
                        {m.title} {m.year ? `· ${m.year}` : ""}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="eyebrow">Recommended for you</span>
          <Pill tone="accent">AI</Pill>
        </div>
        <div className="panel">
          <EmptyState
            title="Recommendations arrive with the AI layer"
            hint={
              <span className="inline-flex items-center gap-1.5">
                <SparkleIcon size={14} /> Taste-based suggestions come once the provider layer is wired.
              </span>
            }
          />
        </div>
      </section>
    </div>
  );
}
