// Storage — where the disk went, ranked by what you would actually get back.
//
// Read-only by design. This ships before anything can act on a finding, because
// the verdicts rest on baselines measured from your own library and those numbers
// deserve to be checked against reality before they drive a delete. The baselines
// panel is here for exactly that.
//
// Duplicate copies come from /api/duplicates, which the backend has served since
// 2607.14.0 with nothing on screen to show it.

import { useCallback, useEffect, useState } from "react";

import { ConfirmModal } from "@/components/ConfirmModal";
import { useToast } from "@/components/Toast";
import { EmptyState, PageTitle, Pill, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useDrawer } from "@/lib/drawer";
import type {
  BaselinesResponse,
  DuplicatesResponse,
  LedgerResponse,
  MovieSizeResponse,
  PlanResponse,
  SizeFinding,
  ShowDuplicates,
  TvStorageResponse,
} from "@/lib/types";

function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(2)} TB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

function fmtRate(bytesPerHour: number): string {
  return `${(bytesPerHour / 1e9).toFixed(2)} GB/h`;
}

function fmtRuntime(ms: number | null): string {
  if (!ms) return "—";
  const total = Math.round(ms / 60000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// Each kind is a different remedy, so each gets its own words rather than a
// single "problem" label that leaves you to work out what to do.
const KIND: Record<string, { label: string; tone: "junk" | "borderline" | "accent"; note: string }> =
  {
    oversized: { label: "Oversized", tone: "borderline", note: "Shrink it" },
    truncated: { label: "Not the film", tone: "junk", note: "Safe to delete" },
    bad_rip: { label: "Bad rip", tone: "accent", note: "Replace it" },
  };

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-fg3">{label}</span>
      <span className="text-2xl font-bold tabular-nums">{value}</span>
      {hint ? <span className="text-xs text-fg2">{hint}</span> : null}
    </div>
  );
}

function FindingRow({ finding, onOpen }: { finding: SizeFinding; onOpen: () => void }) {
  const kind = KIND[finding.kind] ?? { label: finding.kind, tone: "accent" as const, note: "" };
  return (
    <div className="flex flex-wrap items-start gap-3 p-3.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={onOpen}
            className="truncate text-left text-sm font-semibold hover:underline"
          >
            {finding.title}
          </button>
          {finding.year ? <span className="text-xs text-fg3">{finding.year}</span> : null}
          <Pill tone={kind.tone}>{kind.label}</Pill>
          {finding.resolution ? <Pill>{finding.resolution}</Pill> : null}
          {finding.video_codec ? <Pill>{finding.video_codec}</Pill> : null}
        </div>
        <ul className="mt-1 flex flex-col gap-0.5 text-xs text-fg2">
          {finding.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
        <span className="text-sm font-bold tabular-nums">{fmtSize(finding.size)}</span>
        <span className="text-xs text-fg3 tabular-nums">{fmtRuntime(finding.duration_ms)}</span>
        {finding.bytes_reclaimable > 0 ? (
          <span className="text-xs font-semibold" style={{ color: "var(--keep)" }}>
            {fmtSize(finding.bytes_reclaimable)} back
          </span>
        ) : (
          <span className="text-xs text-fg3">{kind.note}</span>
        )}
      </div>
    </div>
  );
}

// The three tiers, in the order they should be worked. Colour carries the
// meaning as well as the label, so the ordering reads at a glance.
const TIER: Record<number, { label: string; tone: "keep" | "borderline" | "junk"; note: string }> = {
  0: { label: "Nothing is lost", tone: "keep", note: "Surplus copies and files that aren't the film" },
  1: { label: "Reversible", tone: "borderline", note: "Re-encodes — the original survives until the new file checks out" },
  2: { label: "A judgement call", tone: "junk", note: "Quality you can't get back without re-downloading" },
};

function TierBoard({ book, plan }: { book: LedgerResponse; plan: PlanResponse | null }) {
  const spent = new Map<string, number>();
  for (const step of plan?.steps ?? []) {
    const key = `${step.finding.target_kind}:${step.finding.target_id}`;
    spent.set(key, step.running_total);
  }
  return (
    <div className="flex flex-col gap-2">
      {book.tiers.map((tier) => {
        const meta = TIER[tier.tier];
        return (
          <div key={tier.tier} className="panel flex flex-wrap items-center gap-3 p-3.5">
            <Pill tone={meta.tone}>{meta.label}</Pill>
            <span className="text-sm font-bold tabular-nums">{fmtSize(tier.bytes_reclaimable)}</span>
            <span className="text-xs text-fg2">
              {tier.count} finding{tier.count === 1 ? "" : "s"} · {meta.note}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// How many paths the confirm dialog lists before it starts counting instead.
// Twenty fills the scroll box; past that the list stops being something anybody
// reads and starts being something they scroll past.
const PATHS_SHOWN = 20;

export function Storage() {
  const [sizes, setSizes] = useState<MovieSizeResponse | null>(null);
  const [dupes, setDupes] = useState<DuplicatesResponse | null>(null);
  const [baselines, setBaselines] = useState<BaselinesResponse | null>(null);
  const [book, setBook] = useState<LedgerResponse | null>(null);
  const [tv, setTv] = useState<TvStorageResponse | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [targetGb, setTargetGb] = useState("500");
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showBaselines, setShowBaselines] = useState(false);
  const [confirming, setConfirming] = useState<ShowDuplicates | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Record<number, string>>({});
  const drawer = useDrawer();
  const toastError = useToast();

  // Whether the server will actually free anything, or only record the intent.
  // This screen files reclaim jobs, so the mode belongs beside the heading rather
  // than one dialog deeper — after a session in staged mode the buttons teach the
  // owner that they are harmless.
  const [dryRun, setDryRun] = useState<boolean | null>(null);
  useEffect(() => {
    api
      .getSettings()
      .then((s) => setDryRun(s.actions_dry_run))
      .catch(() => setDryRun(true));
  }, []);

  const load = useCallback((live: () => boolean) => {
    setError(null);
    return Promise.all([
      api.movieSizes(),
      api.duplicates(),
      api.baselines(),
      api.ledger(),
      api.tvStorage(),
    ])
      .then(([s, d, b, l, t]) => {
        if (!live()) return;
        setSizes(s);
        setDupes(d);
        setBaselines(b);
        setBook(l);
        setTv(t);
      })
      .catch(
        (e: unknown) =>
          live() &&
          setError(
            (e as { message?: string })?.message || "Couldn't read storage figures.",
          ),
      );
  }, []);

  useEffect(() => {
    let live = true;
    const alive = () => live;
    void load(alive);
    // A scan rebuilds every figure on this page, so a finished scan refetches
    // them — refetch rather than reload, so scroll position and anything the
    // owner has half-armed survive.
    const onScanned = () => void load(alive);
    window.addEventListener("sift:scan-complete", onScanned);
    return () => {
      live = false;
      window.removeEventListener("sift:scan-complete", onScanned);
    };
  }, [load]);

  async function makePlan() {
    const gb = Number(targetGb);
    if (!Number.isFinite(gb) || gb <= 0) return;
    setPlanning(true);
    try {
      setPlan(await api.reclaimPlan(Math.round(gb * 1e9)));
    } catch (e) {
      setError((e as { message?: string })?.message || "Couldn't work out a plan.");
    } finally {
      setPlanning(false);
    }
  }

  async function removeSurplus(show: ShowDuplicates) {
    setBusy(true);
    try {
      const result = await api.actOnFinding({
        target_kind: "show",
        target_id: String(show.tvdb_id),
        paths: show.surplus_paths,
        label: `${show.title} — ${show.surplus} surplus episode file(s)`,
      });
      // Proposed, not done: it needs your approval on Activity, and then the
      // agent on your media box has to pick it up. Say so rather than implying
      // the space is already back.
      setDone((d) => ({ ...d, [show.tvdb_id]: result.detail }));
      setConfirming(null);
    } catch (e) {
      toastError((e as { message?: string })?.message || "Couldn't queue that removal.");
    } finally {
      setBusy(false);
    }
  }

  const loading = !sizes && !error;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <PageTitle
          title="Storage"
          subhead="Where the disk went, ranked by what you would actually get back. Nothing here removes anything — findings become actions on the Junk screen, one approval at a time."
        />
        {dryRun !== null && (
          <div>
            <Pill tone={dryRun ? "keep" : "junk"}>
              {dryRun ? "Staged — nothing is deleted" : "Live — deletes are real"}
            </Pill>
          </div>
        )}
      </div>

      {error ? (
        <div className="panel p-4 text-sm" style={{ color: "var(--junk)" }}>
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="panel flex flex-col gap-3 p-4" aria-busy="true">
          <span className="sr-only" role="status">
            Reading storage figures
          </span>
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : null}

      {sizes ? (
        <div className="panel flex flex-wrap gap-8 p-4">
          <Stat
            label="Reclaimable"
            value={fmtSize(sizes.total_reclaimable)}
            hint="from film files alone"
          />
          <Stat
            label="Surplus copies"
            value={String(dupes?.total_surplus ?? 0)}
            hint="every film still kept"
          />
          <Stat label="Oversized" value={String(sizes.oversized_count)} hint="worth shrinking" />
          <Stat
            label="Not the film"
            value={String(sizes.truncated_count)}
            hint="samples and part downloads"
          />
          <Stat
            label="Short films"
            value={String(sizes.short_films_cleared)}
            hint="checked and left alone"
          />
          {tv ? (
            <Stat
              label="TV reclaimable"
              value={fmtSize(tv.duplicate_bytes + tv.season_excess_bytes)}
              hint="duplicate episodes and heavy seasons"
            />
          ) : null}
        </div>
      ) : null}

      {book && book.items.length > 0 ? (
        <section className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">
              What to do, in order
            </h2>
            <p className="max-w-prose text-sm text-fg2">
              Safest first, not biggest first. Most of the space comes back before you have to make
              a single decision about quality.
            </p>
          </div>

          <TierBoard book={book} plan={plan} />

          <div className="panel flex flex-wrap items-end gap-3 p-3.5">
            <label className="flex flex-col gap-1 text-xs font-semibold uppercase tracking-wide text-fg3">
              How much do you need back?
              <span className="flex items-center gap-2">
                <input
                  type="number"
                  min="1"
                  value={targetGb}
                  onChange={(e) => setTargetGb(e.target.value)}
                  className="w-28 rounded-md border border-line bg-bg2 px-2 py-1.5 text-sm tabular-nums text-fg"
                />
                <span className="text-sm font-normal normal-case text-fg2">GB</span>
              </span>
            </label>
            <button
              onClick={() => void makePlan()}
              disabled={planning}
              className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
            >
              {planning ? "Working it out…" : "Work out a plan"}
            </button>
            {plan ? (
              <span className="text-sm text-fg2">
                {plan.reached ? (
                  <>
                    <strong>{plan.steps.length}</strong> steps free{" "}
                    <strong>{fmtSize(plan.total)}</strong> — reaching{" "}
                    <em>{TIER[plan.highest_tier].label.toLowerCase()}</em>.
                  </>
                ) : (
                  <>
                    Everything found comes to <strong>{fmtSize(plan.total)}</strong>, which is short
                    of that. Nothing here can free more.
                  </>
                )}
              </span>
            ) : null}
          </div>

          <div className="panel divide-y divide-line">
            {(plan ? plan.steps.map((s) => s.finding) : book.items).map((finding) => {
              const meta = TIER[finding.risk_tier];
              return (
                <div
                  key={`${finding.kind}-${finding.target_kind}-${finding.target_id}`}
                  className="flex flex-wrap items-start gap-3 p-3.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold">{finding.title}</span>
                      <Pill tone={meta.tone}>{meta.label}</Pill>
                    </div>
                    <p className="mt-0.5 text-xs text-fg2">{finding.detail}</p>
                    <ul className="mt-1 flex flex-col gap-0.5 text-xs text-fg3">
                      {finding.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                  <span className="shrink-0 text-sm font-bold tabular-nums">
                    {fmtSize(finding.bytes_reclaimable)}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {sizes && sizes.items.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">Film files</h2>
          <div className="panel divide-y divide-line">
            {sizes.items.map((finding) => (
              <FindingRow
                key={`${finding.tmdb_id}-${finding.path ?? ""}`}
                finding={finding}
                onOpen={() => drawer.open(finding.tmdb_id)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {sizes && sizes.items.length === 0 && !error ? (
        <EmptyState
          title="Nothing is out of place"
          hint="Every film file is about the size it should be for its length, resolution and codec."
        />
      ) : null}

      {dupes && dupes.items.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">
            Films held more than once
          </h2>
          <p className="text-sm text-fg2">
            The safest space there is — every film survives, only the surplus copies go.
          </p>
          <div className="panel divide-y divide-line">
            {dupes.items.map((group) => (
              <div key={group.tmdb_id} className="flex items-center gap-3 p-3.5">
                <button
                  onClick={() => drawer.open(group.tmdb_id)}
                  className="min-w-0 flex-1 truncate text-left text-sm font-semibold hover:underline"
                >
                  {group.title}
                  {group.year ? <span className="ml-2 text-xs text-fg3">{group.year}</span> : null}
                </button>
                <span className="text-xs text-fg2">
                  {group.copies.length} copies in{" "}
                  {[...new Set(group.copies.map((c) => c.library_section ?? "?"))].join(", ")}
                </span>
                <Pill tone="borderline">{group.surplus} could go</Pill>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {tv && tv.duplicates.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">
            Shows holding the same episode twice
          </h2>
          <p className="max-w-prose text-sm text-fg2">
            Ranked by what you would get back, not by how many copies there are — two duplicated
            hours of 1080p beat six duplicated SD ones. Episodes split across two files are
            excluded; both halves are needed.
          </p>
          <div className="panel divide-y divide-line">
            {tv.duplicates.map((show) => (
              <div key={show.tvdb_id} className="flex flex-wrap items-start gap-3 p-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold">{show.title}</span>
                    {show.library_section ? (
                      <span className="text-xs text-fg3">{show.library_section}</span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-xs text-fg2">
                    {show.episodes.length} episode{show.episodes.length === 1 ? "" : "s"} affected ·{" "}
                    {show.surplus} file{show.surplus === 1 ? "" : "s"} could go
                  </p>
                  <p className="mt-0.5 text-xs text-fg3">
                    {show.episodes
                      .slice(0, 6)
                      .map((e) => `S${e.season_number}E${e.episode_number}`)
                      .join(", ")}
                    {show.episodes.length > 6 ? ` +${show.episodes.length - 6} more` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-sm font-bold tabular-nums">
                    {fmtSize(show.bytes_reclaimable)}
                  </span>
                  {done[show.tvdb_id] ? (
                    <span className="max-w-56 text-right text-xs text-fg2">
                      {done[show.tvdb_id]}
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirming(show)}
                      disabled={show.surplus_paths.length === 0}
                      className="rounded-md px-3 py-1.5 text-xs font-bold disabled:opacity-50"
                      style={{ background: "var(--junk)", color: "var(--accent-fg)" }}
                    >
                      Remove {show.surplus} surplus file{show.surplus === 1 ? "" : "s"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {tv && tv.seasons.some((s) => s.bloated) ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">
            Seasons heavier than their peers
          </h2>
          <p className="max-w-prose text-sm text-fg2">
            Measured per hour, so a 24-episode season is not penalised for being long and a
            55-minute drama is not penalised for being slower than a sitcom.
          </p>
          <div className="panel divide-y divide-line">
            {tv.seasons
              .filter((s) => s.bloated)
              .map((season) => (
                <div
                  key={`${season.tvdb_id}-${season.season_number}`}
                  className="flex flex-wrap items-start gap-3 p-3.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-semibold">{season.title}</span>
                      <span className="text-xs text-fg3">season {season.season_number}</span>
                      {season.air_year ? (
                        <span className="text-xs text-fg3">{season.air_year}</span>
                      ) : null}
                      {season.resolution ? <Pill>{season.resolution}</Pill> : null}
                      {season.video_codec ? <Pill>{season.video_codec}</Pill> : null}
                    </div>
                    <p className="mt-0.5 text-xs text-fg2">
                      {fmtSize(season.total_bytes)} over {season.episode_count} episodes ·{" "}
                      {fmtRate(season.bytes_per_hour)} · {fmtSize(season.per_episode)}/episode
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-0.5 text-right">
                    <span className="text-sm font-bold tabular-nums">{fmtSize(season.excess)}</span>
                    <span className="text-xs text-fg3">over the norm</span>
                  </div>
                </div>
              ))}
          </div>
        </section>
      ) : null}

      {tv && tv.inconsistencies.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-bold uppercase tracking-wide text-fg2">
            Seasons that disagree with themselves
          </h2>
          <p className="max-w-prose text-sm text-fg2">
            An all-SD season is a decision. One SD episode among nineteen HD ones is an accident —
            and it usually costs a little space to put right rather than saving any, which is why
            it sits outside the list above.
          </p>
          <div className="panel divide-y divide-line">
            {tv.inconsistencies.map((odd) => (
              <div
                key={`${odd.tvdb_id}-${odd.season_number}`}
                className="flex flex-wrap items-start gap-3 p-3.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold">{odd.title}</span>
                    <span className="text-xs text-fg3">season {odd.season_number}</span>
                    {odd.common_resolution ? <Pill>{odd.common_resolution}</Pill> : null}
                  </div>
                  <ul className="mt-1 flex flex-col gap-0.5 text-xs text-fg2">
                    {odd.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
                <Pill tone="borderline">
                  {odd.episodes_affected} episode{odd.episodes_affected === 1 ? "" : "s"}
                </Pill>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <ConfirmModal
        open={confirming !== null}
        title={`Remove ${confirming?.surplus ?? 0} surplus file(s) from ${confirming?.title ?? ""}?`}
        confirmLabel="Queue removal"
        busy={busy}
        onCancel={() => setConfirming(null)}
        onConfirm={() => confirming && void removeSurplus(confirming)}
        body={
          <div className="flex flex-col gap-2">
            <p className="text-sm">
              Every episode stays. Only the extra copies go, and the best copy of each is kept.
            </p>
            <p className="rounded-md border border-line bg-bg2 p-2.5 text-xs text-fg2">
              This records the request and needs your approval on <strong>Activity</strong> before
              anything happens. The files are then removed by the agent on your media box — Sift has
              no access to them — and it moves them to a trash folder rather than deleting them, so
              a mistake is recoverable.
            </p>
            {/* The list is capped, and the cap says so. A dialog that shows
                twenty paths out of forty-five, under a heading that says
                forty-five, invites the reading that twenty is the whole set —
                and this is the dialog where that reading gets files removed.
                A truncation nobody is told about is the same failure as no
                truncation at all, only quieter. */}
            <ul className="max-h-40 overflow-y-auto text-xs text-fg3">
              {(confirming?.surplus_paths ?? []).slice(0, PATHS_SHOWN).map((path) => (
                <li key={path} className="truncate">
                  {path}
                </li>
              ))}
              {(confirming?.surplus_paths ?? []).length > PATHS_SHOWN && (
                <li className="pt-1 font-semibold text-fg2">
                  and {(confirming?.surplus_paths ?? []).length - PATHS_SHOWN} more not
                  listed here
                </li>
              )}
            </ul>
          </div>
        }
      />

      {baselines && baselines.buckets.length > 0 ? (
        <section className="flex flex-col gap-2">
          <button
            onClick={() => setShowBaselines((v) => !v)}
            className="self-start text-sm font-bold uppercase tracking-wide text-fg2 hover:underline"
            aria-expanded={showBaselines}
          >
            {showBaselines ? "Hide" : "Show"} what counts as normal here
          </button>
          {showBaselines ? (
            <>
              <p className="max-w-prose text-sm text-fg2">
                Every verdict above compares a file with others of its resolution and codec. These
                are those figures, measured from your own library. Where a row says “seeded”, there
                were too few files of that kind to measure and a default was used instead.
              </p>
              <div className="panel overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-fg3">
                      <th className="p-3 font-semibold">Resolution</th>
                      <th className="p-3 font-semibold">Codec</th>
                      <th className="p-3 font-semibold">Typical rate</th>
                      <th className="p-3 font-semibold">Files</th>
                    </tr>
                  </thead>
                  <tbody>
                    {baselines.buckets.map((b) => (
                      <tr key={`${b.resolution}-${b.codec}`} className="border-t border-line">
                        <td className="p-3 font-semibold">{b.resolution}</td>
                        <td className="p-3">{b.codec}</td>
                        <td className="p-3 tabular-nums">{fmtRate(b.median_rate)}</td>
                        <td className="p-3 tabular-nums">
                          {b.observed ? b.samples : <span className="text-fg3">seeded</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
