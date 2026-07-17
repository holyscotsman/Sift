// Junk — deterministic removal queue. Every removal is approval-gated; the score
// and signals come from the backend (data decides, never AI). Whether an approved
// removal is actually issued to Radarr or merely staged depends on the server's
// dry-run switch (SIFT_ACTIONS__DRY_RUN) — the UI reflects whichever is in effect.

import { useEffect, useMemo, useState } from "react";

import { ChevronDown, ChevronRight } from "@/components/icons";
import { ConfirmModal } from "@/components/ConfirmModal";
import { EmptyState, Pill, Poster, RingGauge, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useDrawer } from "@/lib/drawer";
import type { JunkCandidate } from "@/lib/types";

type Decision = "kept" | "removed_live" | "removed_staged";

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

export function Junk() {
  const [items, setItems] = useState<JunkCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [modal, setModal] = useState<{ candidates: JunkCandidate[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [dryRun, setDryRun] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [reviewMsg, setReviewMsg] = useState<string | null>(null);

  async function runReview() {
    setReviewing(true);
    setReviewMsg(null);
    try {
      const r = await api.runReview();
      const src =
        r.provider === "deterministic"
          ? "no AI configured — showing the deterministic reason"
          : `via ${r.provider}`;
      setReviewMsg(`Reviewed ${r.reviewed} title(s) ${src}.`);
      const fresh = await api.junk();
      setItems(fresh.items);
    } catch {
      setReviewMsg("AI review failed — check your Ollama/Anthropic settings.");
    } finally {
      setReviewing(false);
    }
  }

  useEffect(() => {
    api
      .junk()
      .then((r) => setItems(r.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
    // Learn whether the server will actually issue deletes or only stage them, so
    // the confirm copy and result labels tell the truth.
    api
      .getSettings()
      .then((s) => setDryRun(s.actions_dry_run))
      .catch(() => setDryRun(true));
  }, []);

  const pending = useMemo(() => items.filter((c) => !decisions[c.tmdb_id]), [items, decisions]);

  // Propose → approve → execute. The engine refuses an unapproved delete, and the
  // server's dry-run switch (not the client) decides whether files are really removed.
  async function removeMovies(candidates: JunkCandidate[]) {
    setBusy(true);
    try {
      for (const c of candidates) {
        const action = await api.proposeAction({
          type: "delete",
          movie_tmdb_id: c.tmdb_id,
          payload: { delete_files: true, title: c.title },
          dry_run: false, // request a live write; the server floor may still stage it
        });
        await api.approveAction(action.id); // records the explicit, required approval
        const done = await api.executeAction(action.id);
        setDecisions((d) => ({
          ...d,
          [c.tmdb_id]: done.dry_run ? "removed_staged" : "removed_live",
        }));
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
        <div className="flex items-center gap-2">
          <button
            onClick={runReview}
            disabled={reviewing || items.length === 0}
            className="gradient-fill rounded-pill px-4 py-1.5 text-sm font-bold shadow-glow disabled:opacity-60"
          >
            {reviewing ? "Reviewing…" : "Run AI review"}
          </button>
          {pending.length > 0 && (
            <button
              onClick={() => setModal({ candidates: pending })}
              className="rounded-pill border border-line px-4 py-1.5 text-sm font-semibold text-fg2 hover:bg-bg2"
            >
              Approve all ({pending.length})
            </button>
          )}
        </div>
      </div>
      {reviewMsg && (
        <p className="mb-3 rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-fg2">
          {reviewMsg}
        </p>
      )}

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
        confirmLabel={dryRun ? "Approve (staged)" : "Approve & remove"}
        busy={busy}
        onCancel={() => setModal(null)}
        onConfirm={() => modal && removeMovies(modal.candidates)}
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
            {dryRun ? (
              <p className="rounded-md border border-line bg-bg2 p-2.5 text-xs text-fg2">
                Removals are <strong>staged (dry-run)</strong> — this records your approval in the
                audit log but does not delete any files. To let Sift issue real deletes, switch to
                Live in <strong>Settings › Autonomy</strong>.
              </p>
            ) : (
              <p
                className="rounded-md border p-2.5 text-xs"
                style={{ borderColor: "var(--junk)", color: "var(--junk)" }}
              >
                Live mode: this will tell Radarr to <strong>delete the file(s)</strong>. This cannot
                be undone.
              </p>
            )}
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
  const { open } = useDrawer();
  return (
    <div className="flex flex-col gap-3 p-4 md:flex-row md:items-start">
      <button
        onClick={() => open(c.tmdb_id)}
        aria-label={`Details for ${c.title}`}
        className="h-24 w-16 shrink-0 overflow-hidden rounded-md"
      >
        <Poster tmdbId={c.tmdb_id} alt="" className="h-full w-full" />
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-display text-base font-bold">{c.title}</span>
          {c.year && <span className="text-sm text-fg3">{c.year}</span>}
          {c.quality && <Pill>{c.quality}</Pill>}
          <span className="text-xs text-fg3">{fmtSize(c.file_size)}</span>
          <Pill tone={bandTone(c.band)}>{c.band}</Pill>
        </div>
        <p className="mt-1.5 text-sm text-fg2">{c.rationale}</p>
        {c.ai_note && (
          <div className="mt-2 rounded-md border-l-2 pl-2.5 text-sm text-fg2" style={{ borderColor: "var(--accent)" }}>
            <span className="mr-1 font-semibold text-accent">AI</span>
            {c.ai_note}
          </div>
        )}

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
              <Pill tone={decision === "kept" ? "keep" : "junk"}>
                {decision === "kept"
                  ? "Kept"
                  : decision === "removed_live"
                    ? "Removed"
                    : "Removal staged"}
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
