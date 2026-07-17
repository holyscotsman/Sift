// Dashboard — the instrument-cluster anchor screen. Wired to real Phase-0 data
// (/api/status, /api/health, /api/activity). Analysis-derived figures (junk score,
// collection gaps) are labeled as pending until the Phase-1 analysis engine lands.

import { Link } from "react-router-dom";

import { HealthOrb } from "@/components/HealthOrb";
import { ScanIcon } from "@/components/icons";
import { EmptyState, Pill, RingGauge, Skeleton } from "@/components/ui";
import { useActivity, useHealth, useStatus } from "@/lib/hooks";
import { useScan } from "@/lib/scan";
import type { Counts } from "@/lib/types";

function healthScore(c: Counts | undefined): number {
  if (!c || c.movies === 0) return 0;
  // Placeholder health: share of the catalog that is owned & not pending review.
  const owned = c.owned / c.movies;
  const clean = 1 - Math.min(1, c.actions_pending / Math.max(c.movies, 1));
  return Math.round((owned * 0.6 + clean * 0.4) * 100);
}

function Segment({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`px-6 py-5 ${className}`}>{children}</div>;
}

export function Dashboard() {
  const { data: status, loading } = useStatus();
  const { data: health } = useHealth();
  const { data: activity } = useActivity(6);
  const { start } = useScan();
  const c = status?.counts;
  const online = health?.services.filter((s) => s.ok).length ?? 0;
  const total = health?.services.length ?? 0;

  const score = healthScore(c);
  const band = score >= 80 ? "Excellent" : score >= 55 ? "Good" : score > 0 ? "Needs work" : "No data";
  const missing = c ? Math.max(0, c.monitored - c.owned) : 0;
  const pending = activity?.filter((a) => a.status === "proposed") ?? [];

  return (
    <div className="page-enter">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
            Dashboard
          </h1>
          <p className="mt-1 text-sm text-fg2">
            {loading
              ? "Loading snapshot…"
              : c && c.movies > 0
                ? `${c.movies.toLocaleString()} titles in the snapshot · ${online}/${total} sources online`
                : "No snapshot yet — run a scan to build one."}
          </p>
        </div>
      </div>

      {/* Instrument cluster: one panel, hairline-divided segments. */}
      <div className="panel grid grid-cols-1 divide-y divide-line lg:grid-cols-[1.6fr_1fr_1.4fr] lg:divide-x lg:divide-y-0">
        <Segment>
          <span className="eyebrow">Library health</span>
          <div className="mt-3 flex items-center gap-5">
            <HealthOrb score={score} />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-display text-xl font-extrabold">{band} standing</span>
                <Pill tone={score >= 55 ? "keep" : "borderline"}>{band}</Pill>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
                <Factor label="In Plex" value={c?.owned ?? 0} dot="var(--keep)" />
                <Factor label="Indexed" value={c?.movies ?? 0} dot="var(--accent)" />
                <Factor label="Monitored" value={c?.monitored ?? 0} dot="var(--borderline)" />
                <Factor label="Collections" value={c?.collections ?? 0} dot="var(--accent2)" />
              </div>
            </div>
          </div>
        </Segment>

        <Segment>
          <span className="eyebrow">In your Plex library</span>
          <div className="mt-2 font-display text-[46px] font-extrabold leading-none">
            {loading ? <Skeleton className="h-11 w-24" /> : (c?.owned ?? 0).toLocaleString()}
          </div>
          <div className="mt-3 flex h-2 overflow-hidden rounded-pill bg-bg2">
            <Bar value={c?.owned ?? 0} total={(c?.owned ?? 0) + missing || 1} color="var(--keep)" />
            <Bar value={missing} total={(c?.owned ?? 0) + missing || 1} color="var(--borderline)" />
          </div>
          <div className="mt-2 flex gap-4 text-xs text-fg3">
            <Legend color="var(--keep)" label={`In Plex ${c?.owned ?? 0}`} />
            <Legend color="var(--borderline)" label={`Wanted in Radarr ${missing}`} />
          </div>
        </Segment>

        <Segment className="flex items-center justify-around gap-2">
          <RingGauge value={c?.monitored ?? 0} max={c?.movies || 1} color="var(--accent)" label={c?.monitored ?? 0} caption="Monitored" />
          <RingGauge value={c?.watch_records ?? 0} max={Math.max(c?.movies || 1, 1)} color="var(--keep)" label={c?.watch_records ?? 0} caption="Watched" />
          <RingGauge value={c?.actions_pending ?? 0} max={Math.max(c?.actions_pending || 1, 1)} color="var(--junk)" label={c?.actions_pending ?? 0} caption="Pending" />
        </Segment>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="panel p-5 lg:col-span-2">
          <span className="eyebrow">Needs your attention</span>
          {(c?.upgrades ?? 0) > 0 && (
            <Link
              to="/library?filter=upgrades"
              className="mt-3 flex items-center gap-3 rounded-md border border-line bg-bg2 px-3 py-2.5 hover:bg-bg3"
            >
              <Pill tone="borderline">↑ upgrade</Pill>
              <span className="text-sm text-fg2">
                {c!.upgrades.toLocaleString()} title{c!.upgrades === 1 ? "" : "s"} below the quality
                cutoff
              </span>
              <span className="ml-auto text-xs font-semibold text-accent">Review</span>
            </Link>
          )}
          {pending.length === 0 && (c?.upgrades ?? 0) === 0 ? (
            <EmptyState title="All caught up" hint="No removals or actions are waiting for approval." />
          ) : (
            <ul className="mt-3 divide-y divide-line">
              {pending.slice(0, 3).map((a) => (
                <li key={a.id} className="flex items-center gap-3 py-3">
                  <Pill tone="junk">{a.type}</Pill>
                  <span className="text-sm text-fg2">Movie #{a.movie_tmdb_id ?? "—"}</span>
                  <Link to="/junk" className="ml-auto text-xs font-semibold text-accent hover:underline">
                    Review
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="panel p-5">
          <span className="eyebrow">Quick actions</span>
          <div className="mt-3 flex flex-col gap-2">
            <button
              onClick={() => void start()}
              className="gradient-fill flex items-center justify-center gap-2 rounded-md py-2 text-sm font-bold shadow-glow"
            >
              <ScanIcon size={15} /> Run scan
            </button>
            <Link to="/library" className="rounded-md border border-line py-2 text-center text-sm font-semibold text-fg2 hover:bg-bg2">
              Browse library
            </Link>
            <Link to="/settings" className="rounded-md border border-line py-2 text-center text-sm font-semibold text-fg2 hover:bg-bg2">
              Settings
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function Factor({ label, value, dot }: { label: string; value: number; dot: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-2 w-2 rounded-pill" style={{ background: dot }} />
      <span className="text-fg3">{label}</span>
      <span className="ml-auto font-semibold text-fg">{value.toLocaleString()}</span>
    </div>
  );
}
function Bar({ value, total, color }: { value: number; total: number; color: string }) {
  return <div style={{ width: `${(value / total) * 100}%`, background: color }} />;
}
function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-pill" style={{ background: color }} />
      {label}
    </span>
  );
}
