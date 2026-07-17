// Missing — collection gaps (deterministic) + taste recommendations (AI, next).

import { useEffect, useState } from "react";

import { CheckIcon, SparkleIcon } from "@/components/icons";
import { EmptyState, Pill, Poster, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { CollectionGap, MissingList, MustHaveItem, RecommendedMovie } from "@/lib/types";

// Titles here aren't in the library (that's the point), so the library drawer would
// 404. Link out to TMDB to preview a title before adding it — the affordance Radarr /
// Overseerr use for the same "not-yet-owned" case.
const tmdbMovieUrl = (tmdbId: number) => `https://www.themoviedb.org/movie/${tmdbId}`;

// The one poster-card used by every not-yet-owned section on this page (must-have,
// curated lists, recommendations) — one place to fix sizing/links/badges.
function PosterCard({
  tmdbId,
  title,
  year,
  subtitle,
  voteAverage,
  footer,
}: {
  tmdbId: number;
  title: string;
  year: number | null;
  subtitle?: string;
  voteAverage?: number | null;
  footer?: React.ReactNode;
}) {
  return (
    <div className="w-[92px]">
      <a
        href={tmdbMovieUrl(tmdbId)}
        target="_blank"
        rel="noopener noreferrer"
        className="block w-full text-left"
        title={`${subtitle ? `${subtitle} — ` : ""}view on TMDB`}
      >
        <div className="relative aspect-[2/3] overflow-hidden rounded-md">
          <Poster tmdbId={tmdbId} alt="" className="h-full w-full opacity-90" />
          {voteAverage != null && voteAverage > 0 && (
            <span className="absolute right-1 top-1 rounded-sm bg-black/60 px-1 text-[10px] font-semibold text-white backdrop-blur">
              {voteAverage.toFixed(1)}
            </span>
          )}
        </div>
        <p className="mt-1 truncate text-[11px] text-fg3">
          {title} {year ? `· ${year}` : ""}
        </p>
        {subtitle && <p className="truncate text-[10px] text-fg3/80">{subtitle}</p>}
      </a>
      <AddButton tmdbId={tmdbId} title={title} />
      {footer}
    </div>
  );
}

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
        <p className="mt-1 text-sm text-fg2">
          What your library is missing — collection gaps, the canon, and titles that match
          your taste.
        </p>
      </div>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="eyebrow">Collection gaps</span>
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

      <MustHaveSection />

      {lists.map((list) => (
        <ListSection key={list.name} list={list} />
      ))}

      <RecommendationsSection />
    </div>
  );
}

// Must-have picks: the AI proposes canon titles, deterministic TMDB gates decide
// what's allowed in (vote floor, rating floor, feature runtime, released, not
// adult) — so nothing fringe or invented can appear here.
function MustHaveSection() {
  const [items, setItems] = useState<MustHaveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function refresh() {
    try {
      const r = await api.mustHaveList();
      setItems(r.items);
    } catch {
      setItems([]);
    }
  }

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, []);

  async function run() {
    setRunning(true);
    setNote(null);
    try {
      const r = await api.mustHaveRun();
      setNote(
        r.added > 0
          ? `Found ${r.added} new must-have${r.added === 1 ? "" : "s"} (${r.provider}).`
          : r.provider === "none"
            ? "Connect TMDB (and optionally an AI provider) in Settings › Connections first."
            : "No new must-haves — your canon coverage looks solid.",
      );
      await refresh();
    } catch {
      setNote("The must-have run failed — check your connections.");
    } finally {
      setRunning(false);
    }
  }

  async function dismiss(item: MustHaveItem) {
    // Optimistic removal; on failure restore the snapshot (a refetch here could
    // itself fail during the same network blip and wipe the whole list).
    const snapshot = items;
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    try {
      await api.mustHaveDismiss(item.id);
    } catch {
      setItems(snapshot);
    }
  }

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="eyebrow">Must-have picks</span>
          <Pill tone="accent">AI proposes · data decides</Pill>
        </div>
        <button
          onClick={run}
          disabled={running}
          className="gradient-fill rounded-pill px-4 py-1.5 text-xs font-bold shadow-glow disabled:opacity-60"
        >
          {running ? "Curating…" : "Find must-haves"}
        </button>
      </div>
      {note && (
        <p className="mb-2 rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-fg2">{note}</p>
      )}
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
            title="No must-have picks yet"
            hint={
              <span className="inline-flex items-center gap-1.5">
                <SparkleIcon size={14} /> Run the curator — it studies your library and proposes
                the canon you're missing. Every pick is validated against TMDB.
              </span>
            }
          />
        </div>
      ) : (
        <div className="panel p-4">
          <div className="flex flex-wrap gap-3">
            {items.map((m) => (
              <PosterCard
                key={m.id}
                tmdbId={m.tmdb_id}
                title={m.title}
                year={m.year}
                subtitle={m.reason}
                voteAverage={m.vote_average}
                footer={
                  <button
                    onClick={() => void dismiss(m)}
                    className="mt-1 w-full rounded-md py-0.5 text-[11px] text-fg3 hover:text-fg"
                  >
                    Not interested
                  </button>
                }
              />
            ))}
          </div>
        </div>
      )}
    </section>
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
              <PosterCard
                key={m.tmdb_id}
                tmdbId={m.tmdb_id}
                title={m.title}
                year={m.year}
                subtitle={m.reason}
                voteAverage={m.vote_average}
              />
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
            <PosterCard key={m.tmdb_id} tmdbId={m.tmdb_id} title={m.title} year={m.year} />
          ))}
        </div>
        <p className="mt-3 text-xs text-fg3">
          Starter list, pending human review — expand or correct it anytime.
        </p>
      </div>
    </section>
  );
}
