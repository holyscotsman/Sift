// Junk — deterministic removal queue. Every removal is approval-gated; the score
// and signals come from the backend (data decides, never AI). Removals are staged
// (dry-run) for now — nothing is deleted until live actions are enabled.

import { useEffect, useMemo, useState } from "react";

import { ChevronDown, ChevronRight } from "@/components/icons";
import { ConfirmModal } from "@/components/ConfirmModal";
import { EmptyState, Pill, RingGauge, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { JunkCandidate } from "@/lib/types";

type Decision = "kept" | "removed";

function bandColor(band: string): string {
  return band === "junk" ? "var(--junk)" : band === "borderline" ? "var(--borderline)" : "var(--keep)";
}
function bandTone(band: string): "junk" | "borderline" | "keep" {
  return band === "junk" ? "junk" : band === "borderline" ? "borderline" : "keep";
}
function fmtSize(bytes: number | null): string {
  if (!bytes) return "—";
  return `${(bytes / 1e9).toFixed(1)} GB`;
}
function posterGradient(id: number): string {
  const hue = (id * 47) % 360;
  return `linear-gradient(155deg, hsl(${hue} 44% 32%), hsl(${(hue + 38) % 360} 40% 15%))`;
}

export function Junk() {
  const [items, setItems] = useState<JunkCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [modal, setModal] = useState<{ candidates: JunkCandidate[] } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .junk()
      .then((r) => setItems(r.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  const pending = useMemo(() => items.filter((c) => !decisions[c.tmdb_id]), [items, decisions]);

  async function stageRemovals(candidates: JunkCandidate[]) {
    setBusy(true);
    try {
      for (const c of candidates) {
        const action = await api.proposeAction({
          type: "delete",
          movie_tmdb_id: c.tmdb_id,
          payload: { delete_files: true, title: c.title },
        });
        await api.approveAction(action.id); // records explicit approval (staged)
        setDecisions((d) => ({ ...d, [c.tmdb_id]: "removed" }));
      }
    } finally {
      setBusy(false);
      setModal(null);
    }
  }

  return (
    <div className="page-enter">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
            Junk — removal queue
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-fg2">
            Sift never deletes on its own — every removal needs your approval. Scores are
            deterministic; kids libraries are guarded and never listed here.
          </p>
        </div>
        {pending.length > 0 && (
          <button
            onClick={() => setModal({ candidates: pending })}
            className="rounded-pill border border-line px-4 py-1.5 text-sm font-semibold text-fg2 hover:bg-bg2"
          >
            Approve all ({pending.length})
          </button>
        )}
      </div>

      {loading ? (
        <div className="panel p-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="mb-2 h-20" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="All caught up"
            hint="Nothing is flagged for removal. Run a scan (with ratings) to refresh."
          />
        </div>
      ) : (
        <div className="panel divide-y divide-line">
          {items.map((c) => (
            <Row
              key={c.tmdb_id}
              candidate={c}
              decision={decisions[c.tmdb_id]}
              expanded={expanded.has(c.tmdb_id)}
              onToggle={() =>
                setExpanded((s) => {
                  const n = new Set(s);
                  n.has(c.tmdb_id) ? n.delete(c.tmdb_id) : n.add(c.tmdb_id);
                  return n;
                })
              }
              onKeep={() => setDecisions((d) => ({ ...d, [c.tmdb_id]: "kept" }))}
              onRemove={() => setModal({ candidates: [c] })}
              onReset={() =>
                setDecisions((d) => {
                  const n = { ...d };
                  delete n[c.tmdb_id];
                  return n;
                })
              }
            />
          ))}
        </div>
      )}

      <ConfirmModal
        open={modal !== null}
        title={`Approve removal of ${modal?.candidates.length ?? 0} title(s)?`}
        confirmLabel="Approve removal"
        busy={busy}
        onCancel={() => setModal(null)}
        onConfirm={() => modal && stageRemovals(modal.candidates)}
        body={
          <div>
            <ul className="mb-3 max-h-40 overflow-y-auto text-sm">
              {modal?.candidates.map((c) => (
                <li key={c.tmdb_id} className="flex justify-between gap-3 py-0.5">
                  <span className="truncate text-fg">{c.title}</span>
                  <span className="shrink-0 text-fg3">{fmtSize(c.file_size)}</span>
                </li>
              ))}
            </ul>
            <p className="rounded-md border border-line bg-bg2 p-2.5 text-xs text-fg2">
              Removals are <strong>staged (dry-run)</strong> for now — this records your approval
              in the audit log but does not delete any files yet. Live Radarr execution is the next
              step.
            </p>
          </div>
        }
      />
    </div>
  );
}

function Row({
  candidate: c,
  decision,
  expanded,
  onToggle,
  onKeep,
  onRemove,
  onReset,
}: {
  candidate: JunkCandidate;
  decision?: Decision;
  expanded: boolean;
  onToggle: () => void;
  onKeep: () => void;
  onRemove: () => void;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 p-4 md:flex-row md:items-start">
      <div
        className="h-24 w-16 shrink-0 rounded-md"
        style={c.poster_url ? { backgroundImage: `url(${c.poster_url})`, backgroundSize: "cover" } : { background: posterGradient(c.tmdb_id) }}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-base font-bold">{c.title}</span>
          {c.year && <span className="text-sm text-fg3">{c.year}</span>}
          {c.quality && <Pill>{c.quality}</Pill>}
          <span className="text-xs text-fg3">{fmtSize(c.file_size)}</span>
          <Pill tone={bandTone(c.band)}>{c.band}</Pill>
        </div>
        <p className="mt-1.5 text-sm text-fg2">{c.rationale}</p>

        <button
          onClick={onToggle}
          className="mt-2 flex items-center gap-1 text-xs font-semibold text-accent"
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Signal breakdown
        </button>
        {expanded && (
          <div className="mt-2 flex flex-col gap-2">
            {c.signals.map((s) => (
              <div key={s.key} className="text-xs">
                <div className="flex justify-between text-fg2">
                  <span>{s.label}</span>
                  <span className="text-fg3">{s.available ? s.detail : "no data"}</span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-pill bg-bg2">
                  <div
                    className="h-full rounded-pill"
                    style={{
                      width: `${Math.round(s.contribution * 100)}%`,
                      background: s.contribution >= 0.6 ? "var(--junk)" : s.contribution >= 0.3 ? "var(--borderline)" : "var(--keep)",
                      opacity: s.available ? 1 : 0.3,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <RingGauge value={c.junk_score} color={bandColor(c.band)} size={56} label={Math.round(c.junk_score)} />
        <div className="flex flex-col gap-1.5">
          {decision ? (
            <>
              <Pill tone={decision === "removed" ? "junk" : "keep"}>
                {decision === "removed" ? "Removal staged" : "Kept"}
              </Pill>
              <button onClick={onReset} className="text-xs text-fg3 hover:text-fg">
                Change
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onKeep}
                className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
              >
                Keep it
              </button>
              <button
                onClick={onRemove}
                className="rounded-md px-3 py-1.5 text-xs font-bold"
                style={{ background: "var(--junk)", color: "var(--accent-fg)" }}
              >
                Approve removal
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
