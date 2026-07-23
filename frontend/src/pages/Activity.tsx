// Activity — the trust surface. A vertical timeline of audited actions from the
// real /api/activity feed, with dry-run payloads. Filter chips by action type.

import { useState } from "react";

import { EmptyState, Pill } from "@/components/ui";
import { useActivity } from "@/lib/hooks";
import type { ActionRecord } from "@/lib/types";

type Filter = "all" | "add" | "monitor" | "unmonitor" | "delete";

const TIER: Record<string, { label: string; tone: "keep" | "borderline" | "junk" | "accent" }> = {
  add: { label: "Auto", tone: "keep" },
  monitor: { label: "Auto", tone: "keep" },
  unmonitor: { label: "Auto + Audit", tone: "borderline" },
  delete: { label: "Approval", tone: "junk" },
};

export function Activity() {
  const { data, loading } = useActivity(80);
  const [filter, setFilter] = useState<Filter>("all");
  const rows = (data ?? []).filter((a) => filter === "all" || a.type === filter);

  return (
    <div className="page-enter">
      <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">Activity</h1>
      <p className="mt-1 text-sm text-fg2">Every action Sift takes, audited — with its dry-run payload.</p>

      <div className="my-4 flex flex-wrap gap-2">
        {(["all", "add", "monitor", "unmonitor", "delete"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-pill px-3 py-1 text-[13px] font-semibold capitalize ${
              filter === f ? "bg-accent-soft text-accent" : "text-fg2 hover:bg-bg2"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {loading ? null : rows.length === 0 ? (
        <div className="panel">
          <EmptyState title="No activity yet" hint="Actions you approve or that run autonomously will appear here." />
        </div>
      ) : (
        <ol className="relative ml-2 border-l border-line pl-6">
          {rows.map((a) => (
            <TimelineEntry key={a.id} action={a} />
          ))}
        </ol>
      )}
    </div>
  );
}

// "2 h ago" beats a wall of absolute timestamps; the exact time stays on hover.
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

function TimelineEntry({ action }: { action: ActionRecord }) {
  const [showPayload, setShowPayload] = useState(false);
  const tier = TIER[action.type] ?? { label: "System", tone: "accent" as const };
  const when = new Date(action.created_at).toLocaleString();
  return (
    <li className="relative pb-6">
      <span
        className="absolute -left-[31px] top-1 grid h-4 w-4 place-items-center rounded-full"
        style={{ background: "var(--bg-3)", boxShadow: "0 0 0 3px var(--bg-0)" }}
      >
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)" }} />
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold capitalize text-fg">{action.type}</span>
        {action.movie_tmdb_id != null && (
          <span className="text-xs text-fg3">#{action.movie_tmdb_id}</span>
        )}
        <Pill tone={tier.tone}>{tier.label}</Pill>
        <Pill>{action.dry_run ? `${action.status} · staged` : action.status}</Pill>
        <span className="text-xs text-fg3" title={when}>
          {relativeTime(action.created_at)} · via {action.actor}
        </span>
        <button
          onClick={() => setShowPayload((v) => !v)}
          className="text-xs font-semibold text-accent"
        >
          {showPayload ? "Hide payload" : "Payload"}
        </button>
      </div>
      {showPayload && (
        <pre className="mt-2 overflow-x-auto rounded-md border border-line bg-panel p-3 font-mono text-[11.5px] text-fg2">
          {JSON.stringify(
            { movie: action.movie_tmdb_id, dry_run: action.dry_run, ...action.payload },
            null,
            2,
          )}
        </pre>
      )}
    </li>
  );
}
