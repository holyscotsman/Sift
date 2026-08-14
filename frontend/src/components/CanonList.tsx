// The canon films you don't own, strongest claim first.
//
// The acquisition half of the two-question model. Junk asks whether a file
// deserves its disk here; this asks whether a film missing from the shelf is
// worth getting. A bad film can be a keep and a fine film can be junk, so these
// are not one axis and this list only ever answers the second question.
//
// The coverage line deliberately reports what is still unresolved. The canon
// arrives keyed by IMDb id and the library by TMDB id, so early on this list is
// shorter than the truth — a bare "2,340 of 10,000" would read as complete when
// most of the list has simply never been looked up.

import { useEffect, useState } from "react";

import { EmptyState, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ValidatedCanonResponse } from "@/lib/types";

const TIER_LABEL: Record<number, string> = {
  1: "Essential",
  2: "Major",
  3: "Notable",
  4: "Well known",
};

const SOURCE_LABEL: Record<string, string> = {
  criterion: "Criterion",
  cult: "Cult",
  award: "Award",
  imdb_wr: "Consensus",
  canon_patch: "Curated",
  floor_override: "Curated",
};

function fmt(n: number): string {
  return n.toLocaleString();
}

export function CanonList() {
  const [data, setData] = useState<ValidatedCanonResponse | null>(null);
  const [tier, setTier] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    api
      .validatedCanon({ tier, limit: 120 })
      .then((r) => live && setData(r))
      .catch((e) => live && setError((e as { message?: string })?.message || "Couldn't load the canon."));
    return () => {
      live = false;
    };
  }, [tier]);

  if (error) {
    return (
      <div className="panel p-4 text-sm" style={{ color: "var(--junk)" }}>
        {error}
      </div>
    );
  }

  const coverage = data?.coverage;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-fg2">
          {coverage
            ? `You have ${fmt(coverage.owned)} of ${fmt(coverage.total)} canon films`
            : "Loading…"}
          {coverage && coverage.unresolved > 0 ? (
            <span className="text-fg3">
              {" "}
              · {fmt(coverage.unresolved)} still being matched up, so this is a floor
            </span>
          ) : null}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={tier ?? ""}
            onChange={(e) => setTier(e.target.value ? Number(e.target.value) : null)}
            className="rounded-md border border-line bg-bg2 px-2 py-1.5 text-sm text-fg"
            aria-label="Tier"
          >
            <option value="">All tiers</option>
            {[1, 2, 3, 4].map((t) => (
              <option key={t} value={t}>
                {TIER_LABEL[t]}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!data ? (
        <div className="panel flex flex-col gap-2 p-4" aria-busy="true">
          <span className="sr-only" role="status">
            Loading the canon
          </span>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : data.items.length === 0 ? (
        <EmptyState
          title={coverage && coverage.resolved === 0 ? "Still matching up the canon" : "Nothing missing"}
          hint={
            coverage && coverage.resolved === 0
              ? "The canon is matched to your library a few hundred titles per scan. Run a scan and check back."
              : "Every canon film that has been matched so far is already on your server."
          }
        />
      ) : (
        <div className="panel divide-y divide-line">
          {data.items.map((item) => (
            <div key={item.tmdb_id} className="flex flex-wrap items-center gap-3 p-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{item.title}</span>
                  {item.year ? <span className="text-xs text-fg3">{item.year}</span> : null}
                  <Pill>{TIER_LABEL[item.tier] ?? `Tier ${item.tier}`}</Pill>
                  {item.spine ? <span className="text-xs text-fg3">Spine {item.spine}</span> : null}
                </div>
                <p className="mt-0.5 text-xs text-fg2">
                  {item.sources.map((s) => SOURCE_LABEL[s] ?? s).join(" · ")}
                  {item.votes ? ` · ${fmt(item.votes)} votes` : ""}
                </p>
              </div>
              <a
                className="shrink-0 rounded-pill border border-line px-3 py-1 text-xs font-semibold text-fg2 hover:bg-bg2"
                href={`https://www.themoviedb.org/movie/${item.tmdb_id}`}
                target="_blank"
                rel="noreferrer"
              >
                View
              </a>
            </div>
          ))}
          {data.total > data.items.length ? (
            <p className="p-3.5 text-xs text-fg3">
              Showing {fmt(data.items.length)} of {fmt(data.total)} missing.
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
