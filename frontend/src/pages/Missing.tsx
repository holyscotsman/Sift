// Missing — collection gaps (deterministic) + taste recommendations (AI, next).

import { useEffect, useState } from "react";

import { CheckIcon, SparkleIcon } from "@/components/icons";
import { EmptyState, Pill, Poster, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { CollectionGap, MissingList, RecommendedMovie } from "@/lib/types";

// Titles here aren't in the library (that's the point), so the library drawer would
// 404. Link out to TMDB to preview a title before adding it — the affordance Radarr /
// Overseerr use for the same "not-yet-owned" case.
const tmdbMovieUrl = (tmdbId: number) => `https://www.themoviedb.org/movie/${tmdbId}`;

// Add-to-Radarr button — autonomous action, staged unless live writes are enabled.
function AddButton({ tmdbId, title }: { tmdbId: number; title: string }) {
  const [label, setLabel] = useState("+ Add");
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  async function add(e: React.MouseEvent) {
    e.stopPropagation();
    setState("busy");
    try {
      const a = await api.addMovie(tmdbId, title);
      setState("done");
      setLabel(a.dry_run ? "Add staged" : "Added ✓");
    } catch {
      setState("idle");
      setLabel("Retry");
    }
  }
  return (
    <button
      onClick={add}
      disabled={state !== "idle"}
      className="mt-1 w-full rounded-md border border-line py-1 text-[11px] font-semibold text-accent hover:bg-bg2 disabled:opacity-70"
    >
      {state === "busy" ? "…" : label}
    </button>
  );
}

export function Missing() {
  const [gaps, setGaps] = useState<CollectionGap[]>([]);
  const [lists, setLists] = useState<MissingList[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.missingCollections().then((r) => setGaps(r.collections)).catch(() => setGaps([])),
      api.missingLists().then((r) => setLists(r.lists)).catch(() => setLists([])),
    ]).finally(() => setLoading(false));
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
                        className="relative aspect-[2/3] overflow-hidden rounded-md"
                        style={m.owned ? undefined : { border: "1.5px dashed var(--line-2)" }}
                      >
                        <Poster
                          tmdbId={m.tmdb_id}
                          alt=""
                          className={`h-full w-full ${m.owned ? "" : "opacity-40 grayscale"}`}
                        />
                        {m.owned ? (
                          <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full" style={{ background: "var(--keep)" }}>
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
                      {!m.owned && <AddButton tmdbId={m.tmdb_id} title={m.title} />}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {lists.map((list) => (
        <ListSection key={list.name} list={list} />
      ))}

      <RecommendationsSection />
    </div>
  );
}

// Taste-based suggestions: TMDB's discovery graph seeded by your highest-rated titles.
// Lazy — only fetched when the section mounts, since it fans out to TMDB.
function RecommendationsSection() {
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
              <div key={m.tmdb_id} className="w-[92px]">
                <a
                  href={tmdbMovieUrl(m.tmdb_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block w-full text-left"
                  title={`${m.reason} — view on TMDB`}
                >
                  <div className="relative aspect-[2/3] overflow-hidden rounded-md">
                    <Poster tmdbId={m.tmdb_id} alt="" className="h-full w-full opacity-90" />
                    {m.vote_average > 0 && (
                      <span className="absolute right-1 top-1 rounded-sm bg-black/60 px-1 text-[10px] font-semibold text-white backdrop-blur">
                        {m.vote_average.toFixed(1)}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-[11px] text-fg3">
                    {m.title} {m.year ? `· ${m.year}` : ""}
                  </p>
                  <p className="truncate text-[10px] text-fg3/80">{m.reason}</p>
                </a>
                <AddButton tmdbId={m.tmdb_id} title={m.title} />
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-fg3">
            Grounded in your highest-rated titles via TMDB — Sift ranks and explains, it
            never invents.
          </p>
        </div>
      )}
    </section>
  );
}

function ListSection({ list }: { list: MissingList }) {
  if (list.items.length === 0) return null;
  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <span className="eyebrow">{list.label} you don't own</span>
        <Pill tone="borderline">{list.items.length}</Pill>
      </div>
      <div className="panel p-4">
        <div className="flex flex-wrap gap-3">
          {list.items.map((m) => (
            <div key={m.tmdb_id} className="w-[92px]">
              <a
                href={tmdbMovieUrl(m.tmdb_id)}
                target="_blank"
                rel="noopener noreferrer"
                className="block w-full text-left"
                title={`${m.title}${m.year ? ` (${m.year})` : ""} — view on TMDB`}
              >
                <div className="relative aspect-[2/3] overflow-hidden rounded-md">
                  <Poster tmdbId={m.tmdb_id} alt="" className="h-full w-full opacity-90" />
                </div>
                <p className="mt-1 truncate text-[11px] text-fg3">
                  {m.title} {m.year ? `· ${m.year}` : ""}
                </p>
              </a>
              <AddButton tmdbId={m.tmdb_id} title={m.title} />
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-fg3">
          Starter list, pending human review — expand or correct it anytime.
        </p>
      </div>
    </section>
  );
}
