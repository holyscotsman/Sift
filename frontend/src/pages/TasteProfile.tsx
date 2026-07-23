// Taste Profile — aggregated breakdown of the library (genres/keywords/people/eras)
// plus editable emphasis weights. The genre and era weights steer the
// Recommended-for-you ranking (bounded reorder — they never gate a title out).

import { useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/Toast";
import { EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ProfileBucket, ProfileResponse, ProfileWeights } from "@/lib/types";

function BarList({ items }: { items: ProfileBucket[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((i) => (
        <div key={i.name} className="flex items-center gap-2 text-sm">
          <span className="w-28 shrink-0 truncate text-fg2">{i.name}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-pill bg-bg2">
            <div
              className="h-full rounded-pill"
              style={{ width: `${(i.count / max) * 100}%`, background: "var(--grad)" }}
            />
          </div>
          <span className="w-6 text-right text-xs text-fg3">{i.count}</span>
        </div>
      ))}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel p-5">
      <span className="eyebrow">{title}</span>
      <div className="mt-3">{children}</div>
    </div>
  );
}

const WEIGHT_LABELS: { key: keyof ProfileWeights; label: string }[] = [
  { key: "genre", label: "Genre" },
  { key: "director", label: "Director" },
  { key: "cast", label: "Cast" },
  { key: "keywords", label: "Keywords" },
  { key: "era", label: "Era" },
];

export function TasteProfile() {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [weights, setWeights] = useState<ProfileWeights | null>(null);
  const [saved, setSaved] = useState(false);
  const toastError = useToast();

  useEffect(() => {
    api
      .getProfile()
      .then((d) => {
        setData(d);
        setWeights(d.weights);
      })
      .catch(() => setData(null));
  }, []);

  const favors = useMemo(() => {
    if (!weights) return "";
    const top = [...WEIGHT_LABELS].sort((a, b) => weights[b.key] - weights[a.key])[0];
    return top.label.toLowerCase();
  }, [weights]);

  if (!data || !weights) {
    return (
      <div className="page-enter">
        <h1 className="mb-4 font-display text-[28px] font-extrabold tracking-tight">Taste Profile</h1>
        <div className="panel p-6">
          <Skeleton className="mb-2 h-6 w-40" />
          <Skeleton className="h-40" />
        </div>
      </div>
    );
  }

  if (data.library_size === 0) {
    return (
      <div className="page-enter">
        <h1 className="mb-4 font-display text-[28px] font-extrabold tracking-tight">Taste Profile</h1>
        <div className="panel">
          <EmptyState title="No library yet" hint="Run a scan to build your taste profile." />
        </div>
      </div>
    );
  }

  return (
    <div className="page-enter">
      <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
        Taste Profile
      </h1>
      <p className="mt-1 text-sm text-fg2">Built from {data.library_size} titles in your library.</p>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-4">
          <Card title="Top genres">
            {data.genres.length ? <BarList items={data.genres} /> : <p className="text-sm text-fg3">—</p>}
          </Card>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card title="Directors">
              {data.directors.length ? (
                <BarList items={data.directors} />
              ) : (
                <p className="text-sm text-fg3">Enrich TMDB metadata to populate people.</p>
              )}
            </Card>
            <Card title="Eras">
              {data.eras.length ? <BarList items={data.eras} /> : <p className="text-sm text-fg3">—</p>}
            </Card>
          </div>
          <Card title="Keywords & themes">
            {data.keywords.length ? (
              <div className="flex flex-wrap gap-1.5">
                {data.keywords.map((k) => (
                  <span
                    key={k.name}
                    className="rounded-pill bg-bg2 px-2.5 py-1 text-fg2"
                    style={{ fontSize: `${Math.min(16, 11 + k.count)}px` }}
                  >
                    {k.name}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-fg3">Enrich TMDB metadata to populate keywords.</p>
            )}
          </Card>
        </div>

        <div className="lg:sticky lg:top-4 lg:self-start">
          <Card title="Emphasis">
            <p className="mb-3 text-sm text-fg2">
              You favor <span className="font-semibold text-accent">{favors}</span>. Genre and
              era emphasis reorder the Missing page&rsquo;s recommendations.
            </p>
            <div className="flex flex-col gap-3">
              {WEIGHT_LABELS.map((w) => (
                <div key={w.key}>
                  <div className="flex justify-between text-sm">
                    <label className="text-fg2">{w.label}</label>
                    <span className="font-mono text-fg">{weights[w.key].toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={weights[w.key]}
                    onChange={(e) => {
                      setSaved(false);
                      setWeights({ ...weights, [w.key]: Number(e.target.value) });
                    }}
                    className="mt-1 w-full accent-[color:var(--accent)]"
                  />
                </div>
              ))}
            </div>
            <button
              onClick={() =>
                api
                  .saveWeights(weights)
                  .then((d) => {
                    setWeights(d.weights);
                    setSaved(true);
                  })
                  .catch(() => toastError("Couldn't save the weights — try again."))
              }
              className="gradient-fill mt-4 w-full rounded-md py-2 text-sm font-bold shadow-glow"
            >
              {saved ? "Saved ✓" : "Save weights"}
            </button>
          </Card>
        </div>
      </div>
    </div>
  );
}
