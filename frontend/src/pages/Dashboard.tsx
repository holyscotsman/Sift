// Dashboard — the instrument-cluster anchor screen. Wired to real Phase-0 data
// (/api/status, /api/health, /api/activity, /api/settings). "Needs your attention"
// is state-driven: actionable queues first, then missing integrations.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { HealthOrb } from "@/components/HealthOrb";
import { ScanIcon } from "@/components/icons";
import { EmptyState, Pill, RingGauge, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useActivity, useHealth, useStatus } from "@/lib/hooks";
import { useScan } from "@/lib/scan";
import { hoursSince, relativeTime } from "@/lib/time";
import type { Counts, SettingsResponse } from "@/lib/types";

interface Deduction {
  label: string;
  points: number;
}

// Deterministic, auditable health: start at 100 and subtract named deductions —
// junk backlog and quality-cutoff share (scaled to the library), plus a small
// fixed hit per missing integration. Every point lost is shown under the orb.
function healthBreakdown(
  c: Counts | undefined,
  s: SettingsResponse | null,
): { score: number; deductions: Deduction[] } {
  if (!c || c.owned === 0) return { score: 0, deductions: [] };
  const deductions: Deduction[] = [];
  const junkPts = Math.min(40, Math.round((c.junk_flagged / c.owned) * 80));
  if (junkPts > 0)
    deductions.push({
      label: `${c.junk_flagged} junk candidate${c.junk_flagged === 1 ? "" : "s"}`,
      points: junkPts,
    });
  const upgradePts = Math.min(20, Math.round((c.upgrades / c.owned) * 40));
  if (upgradePts > 0)
    deductions.push({
      label: `${c.upgrades} below quality cutoff`,
      points: upgradePts,
    });
  const unconfigured = (svc: string) => {
    const conn = s?.connections.find((x) => x.service === svc);
    return conn ? !conn.ok && ["disabled", "not configured"].includes(conn.detail) : false;
  };
  if (unconfigured("tmdb")) deductions.push({ label: "TMDB not connected", points: 5 });
  if (unconfigured("tautulli")) deductions.push({ label: "Tautulli not connected", points: 5 });
  if (s && !s.ai_configured) deductions.push({ label: "No AI provider", points: 5 });
  const score = Math.max(0, 100 - deductions.reduce((sum, d) => sum + d.points, 0));
  return { score, deductions };
}

function Segment({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`px-6 py-5 ${className}`}>{children}</div>;
}

interface Attention {
  key: string;
  tone: "keep" | "borderline" | "junk" | "accent" | "neutral";
  pill: string;
  text: string;
  to: string;
  cta: string;
}

// Actionable queues first (things to review), then missing integrations that
// silently degrade features, worst first. Unconfigured ≠ unreachable — a service
// that is set up but momentarily down doesn't earn a "connect it" card.
function buildAttention(c: Counts | undefined, s: SettingsResponse | null): Attention[] {
  const items: Attention[] = [];
  const notConnected = (svc: string) => {
    const conn = s?.connections.find((x) => x.service === svc);
    return conn ? !conn.ok && ["disabled", "not configured"].includes(conn.detail) : false;
  };
  if ((c?.junk_flagged ?? 0) > 0)
    items.push({
      key: "junk", tone: "junk", pill: "junk",
      text: `${c!.junk_flagged.toLocaleString()} title${c!.junk_flagged === 1 ? "" : "s"} flagged for review`,
      to: "/junk", cta: "Review",
    });
  if ((c?.musthave_pending ?? 0) > 0)
    items.push({
      key: "musthave", tone: "accent", pill: "must-have",
      text: `${c!.musthave_pending.toLocaleString()} must-have pick${c!.musthave_pending === 1 ? "" : "s"} waiting`,
      to: "/missing", cta: "Browse",
    });
  if ((c?.upgrades ?? 0) > 0)
    items.push({
      key: "upgrades", tone: "borderline", pill: "↑ upgrade",
      text: `${c!.upgrades.toLocaleString()} title${c!.upgrades === 1 ? "" : "s"} below the quality cutoff`,
      to: "/library?filter=upgrades", cta: "Review",
    });
  if (s?.ephemeral_risk)
    items.push({
      key: "storage", tone: "junk", pill: "storage",
      text: "SQLite on an ephemeral disk — login and settings reset on redeploy",
      to: "/settings", cta: "Fix",
    });
  if (notConnected("tmdb"))
    items.push({
      key: "tmdb", tone: "borderline", pill: "setup",
      text: "TMDB isn't connected — posters, ratings and Must-Haves need it",
      to: "/settings", cta: "Connect",
    });
  if (notConnected("tautulli"))
    items.push({
      key: "tautulli", tone: "neutral", pill: "setup",
      text: "Tautulli isn't connected — watch history sharpens junk scoring",
      to: "/settings", cta: "Connect",
    });
  if (s && !s.ai_configured)
    items.push({
      key: "ai", tone: "neutral", pill: "AI",
      text: "No AI provider linked — Ask works, but reviews stay unphrased",
      to: "/settings", cta: "Link",
    });
  return items;
}

export function Dashboard() {
  const { data: status, loading } = useStatus();
  const { data: health } = useHealth();
  const { data: activity } = useActivity(6);
  const { start } = useScan();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const c = status?.counts;
  const online = health?.services.filter((s) => s.ok).length ?? 0;
  const total = health?.services.length ?? 0;

  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((s) => {
        if (!cancelled) setSettings(s);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const { score, deductions } = healthBreakdown(c, settings);
  const band = score >= 80 ? "Excellent" : score >= 55 ? "Good" : score > 0 ? "Needs work" : "No data";
  const missing = c ? Math.max(0, c.monitored - c.owned) : 0;
  const pending = activity?.filter((a) => a.status === "proposed") ?? [];
  const attention = buildAttention(c, settings);

  // Snapshot freshness: how old the data on this screen is, and a stale hint when
  // it has outlived twice the configured rescan interval.
  const finished = status?.last_scan_finished_at ?? null;
  const interval = settings?.scan_interval_hours ?? 0;
  const stale = finished != null && interval > 0 && hoursSince(finished) > interval * 2;

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
            {!loading && finished && (
              <span className="text-fg3" title={new Date(finished).toLocaleString()}>
                {" "}
                · refreshed {relativeTime(finished)}
                {stale && (
                  <span style={{ color: "var(--borderline)" }}> · snapshot may be stale</span>
                )}
              </span>
            )}
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
              {/* The score is auditable: every point lost is named here. */}
              {score > 0 && deductions.length === 0 ? (
                <p className="mt-3 text-[13px] text-fg3">
                  No deductions — nothing flagged, nothing missing.
                </p>
              ) : (
                <div className="mt-3 flex flex-col gap-1 text-[13px]">
                  {deductions.slice(0, 4).map((d) => (
                    <div key={d.label} className="flex items-center gap-2">
                      <span className="font-mono font-semibold" style={{ color: "var(--borderline)" }}>
                        −{d.points}
                      </span>
                      <span className="text-fg3">{d.label}</span>
                    </div>
                  ))}
                  {score === 0 && deductions.length === 0 && (
                    <span className="text-fg3">Run a scan to measure library health.</span>
                  )}
                </div>
              )}
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
          {/* Denominators that mean something: share of catalog monitored, share of
              owned titles ever watched, and pending actions against the whole
              actionable queue (the ring drains as the queue is worked). */}
          <RingGauge value={c?.monitored ?? 0} max={c?.movies || 1} color="var(--accent)" label={c?.monitored ?? 0} caption="Monitored" />
          <RingGauge value={c?.watched_titles ?? 0} max={c?.owned || 1} color="var(--keep)" label={c?.watched_titles ?? 0} caption="Watched" />
          <RingGauge
            value={c?.actions_pending ?? 0}
            max={Math.max((c?.actions_pending ?? 0) + (c?.junk_flagged ?? 0) + (c?.upgrades ?? 0), 1)}
            color="var(--junk)"
            label={c?.actions_pending ?? 0}
            caption="Pending"
          />
        </Segment>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="panel p-5 lg:col-span-2">
          <span className="eyebrow">Needs your attention</span>
          {attention.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              {attention.slice(0, 4).map((a) => (
                <Link
                  key={a.key}
                  to={a.to}
                  className="flex items-center gap-3 rounded-md border border-line bg-bg2 px-3 py-2.5 hover:bg-bg3"
                >
                  <Pill tone={a.tone}>{a.pill}</Pill>
                  <span className="text-sm text-fg2">{a.text}</span>
                  <span className="ml-auto shrink-0 text-xs font-semibold text-accent">{a.cta}</span>
                </Link>
              ))}
            </div>
          )}
          {pending.length === 0 && attention.length === 0 ? (
            <EmptyState
              title="All caught up"
              hint="No removals or actions are waiting for approval."
              action={
                <button
                  onClick={() => void start()}
                  className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
                >
                  Refresh the snapshot
                </button>
              }
            />
          ) : (
            pending.length > 0 && (
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
            )
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
