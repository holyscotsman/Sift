// Taste-based suggestions: TMDB's discovery graph seeded by your highest-rated
// titles, reordered by the Taste Profile's emphasis sliders. Lives on the Taste
// Profile page — it's a taste surface, not a canon one.

import { useEffect, useState } from "react";

import { SparkleIcon } from "@/components/icons";
import { RequestCard } from "@/components/RequestCard";
import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { RecommendedMovie } from "@/lib/types";

export function RecommendationsSection() {
  const [items, setItems] = useState<RecommendedMovie[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .missingRecommendations()
      .then((r) => {
        setItems(r.items);
        setNote(r.note);
      })
      .catch(() => setNote("Recommendations are unavailable right now."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <span className="eyebrow">Recommended for you</span>
        <Pill tone="accent">Taste graph</Pill>
      </div>
      {loading ? (
        <div className="panel p-4">
          <div className="flex flex-wrap gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-[138px] w-[92px]" />
            ))}
          </div>
        </div>
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="No recommendations yet"
            hint={
              <span className="inline-flex items-center gap-1.5">
                <SparkleIcon size={14} />
                {note ?? "Run a scan and connect TMDB to surface titles that match your taste."}
              </span>
            }
          />
        </div>
      ) : (
        <div className="panel p-4">
          <div className="flex flex-wrap gap-3">
            {items.map((m) => (
              <RequestCard
                key={m.tmdb_id}
                tmdbId={m.tmdb_id}
                title={m.title}
                year={m.year}
                subtitle={m.reason}
                voteAverage={m.vote_average}
                width={92}
              />
            ))}
          </div>
          <p className="mt-3 text-xs text-fg3">
            Grounded in your highest-rated titles via TMDB — Sift ranks and explains, it never
            invents.
          </p>
        </div>
      )}
    </section>
  );
}
