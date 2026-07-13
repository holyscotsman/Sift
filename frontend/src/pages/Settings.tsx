// Settings — appearance (theme/accent/density/motion), connection status with test,
// scoring thresholds with live "would flag N" preview, and the autonomy tiers.

import { useCallback, useEffect, useRef, useState } from "react";

import { LockIcon } from "@/components/icons";
import { Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { ServiceHealth, ThresholdPreview, Thresholds } from "@/lib/types";

const TABS = ["Appearance", "Connections", "Scoring", "Autonomy"] as const;
type Tab = (typeof TABS)[number];

const ACCENTS = ["#2ee6e6", "#92dd23", "#7855fa", "#ff6b5b", "#ffc857", "#1fdde9"];

export function Settings() {
  const [tab, setTab] = useState<Tab>("Appearance");
  return (
    <div className="page-enter">
      <h1 className="mb-4 font-display text-[28px] font-extrabold tracking-tight md:text-[30px]">
        Settings
      </h1>
      <div className="flex flex-col gap-5 md:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto md:w-[200px] md:flex-col">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-2 text-left text-sm font-semibold ${
                tab === t ? "bg-accent-soft text-accent" : "text-fg2 hover:bg-bg2"
              }`}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          {tab === "Appearance" && <Appearance />}
          {tab === "Connections" && <Connections />}
          {tab === "Scoring" && <Scoring />}
          {tab === "Autonomy" && <Autonomy />}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel mb-4 p-5">
      <span className="eyebrow">{title}</span>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function Appearance() {
  const { theme, setTheme, accent, setAccent, density, toggleDensity, reduceMotion, setReduceMotion } =
    usePrefs();
  return (
    <>
      <Section title="Theme">
        <div className="flex gap-2">
          {(["dark", "light", "neon"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={`rounded-md border px-4 py-2 text-sm font-semibold capitalize ${
                theme === t ? "border-accent-line text-accent" : "border-line text-fg2 hover:bg-bg2"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </Section>
      <Section title="Accent color">
        <div className="flex flex-wrap items-center gap-2">
          {ACCENTS.map((hex) => (
            <button
              key={hex}
              onClick={() => setAccent(hex)}
              aria-label={`accent ${hex}`}
              className="h-8 w-8 rounded-full ring-offset-2 ring-offset-panel"
              style={{ background: hex, boxShadow: accent === hex ? `0 0 0 2px var(--fg)` : "none" }}
            />
          ))}
          <button
            onClick={() => setAccent(null)}
            className="rounded-md border border-line px-3 py-1.5 text-xs text-fg2 hover:bg-bg2"
          >
            Reset
          </button>
        </div>
        <p className="mt-2 text-xs text-fg3">Sift derives a matching duotone via a +58° hue shift.</p>
      </Section>
      <Section title="Density">
        <button
          onClick={toggleDensity}
          className="rounded-md border border-line px-4 py-2 text-sm font-semibold capitalize text-fg2 hover:bg-bg2"
        >
          {density}
        </button>
      </Section>
      <Section title="Reduce motion">
        <label className="flex items-center gap-3 text-sm text-fg2">
          <input type="checkbox" checked={reduceMotion} onChange={(e) => setReduceMotion(e.target.checked)} />
          Pause the aurora, tilt, and orb animations
        </label>
      </Section>
    </>
  );
}

function Connections() {
  const [rows, setRows] = useState<ServiceHealth[]>([]);
  const [testing, setTesting] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => setRows(s.connections)).catch(() => setRows([]));
  }, []);

  async function test(service: string) {
    setTesting(service);
    try {
      const r = await api.testConnection(service);
      setRows((rs) => rs.map((x) => (x.service === service ? r : x)));
    } finally {
      setTesting(null);
    }
  }

  return (
    <Section title="Connections">
      <div className="divide-y divide-line">
        {rows.map((r) => (
          <div key={r.service} className="flex items-center gap-3 py-3">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: r.ok ? "var(--keep)" : "var(--fg-3)" }}
            />
            <span className="w-24 text-sm font-semibold capitalize">{r.service}</span>
            <span className="flex-1 truncate text-xs text-fg3">{r.detail}</span>
            {r.service !== "model" && (
              <button
                onClick={() => test(r.service)}
                disabled={testing === r.service}
                className="rounded-md border border-line px-2.5 py-1 text-xs text-fg2 hover:bg-bg2 disabled:opacity-50"
              >
                {testing === r.service ? "Testing…" : "Test"}
              </button>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-fg3">
        Connection URLs and keys are set as environment variables on the server.
      </p>
    </Section>
  );
}

const SLIDERS: { key: keyof Thresholds; label: string; min: number; max: number; step: number }[] = [
  { key: "min_votes", label: "Minimum vote count", min: 0, max: 500, step: 10 },
  { key: "rating_floor", label: "Rating floor (/10)", min: 0, max: 10, step: 0.1 },
  { key: "unwatched_years", label: "Not-watched years", min: 1, max: 10, step: 1 },
  { key: "borderline_cutoff", label: "Borderline cutoff", min: 0, max: 100, step: 1 },
  { key: "junk_cutoff", label: "Junk cutoff", min: 0, max: 100, step: 1 },
];

function Scoring() {
  const [thr, setThr] = useState<Thresholds | null>(null);
  const [preview, setPreview] = useState<ThresholdPreview | null>(null);
  const [saved, setSaved] = useState(false);
  const timer = useRef<number>();

  useEffect(() => {
    api.getSettings().then((s) => setThr(s.thresholds)).catch(() => {});
  }, []);

  const runPreview = useCallback((t: Thresholds) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api.previewThresholds(t).then(setPreview).catch(() => setPreview(null));
    }, 250);
  }, []);

  useEffect(() => {
    if (thr) runPreview(thr);
  }, [thr, runPreview]);

  if (!thr) return <Section title="Scoring thresholds">Loading…</Section>;

  return (
    <Section title="Scoring thresholds">
      <div className="flex flex-col gap-4">
        {SLIDERS.map((s) => (
          <div key={s.key}>
            <div className="flex justify-between text-sm">
              <label className="text-fg2">{s.label}</label>
              <span className="font-mono text-fg">{thr[s.key]}</span>
            </div>
            <input
              type="range"
              min={s.min}
              max={s.max}
              step={s.step}
              value={thr[s.key]}
              onChange={(e) => {
                setSaved(false);
                setThr({ ...thr, [s.key]: Number(e.target.value) });
              }}
              className="mt-1 w-full accent-[color:var(--accent)]"
            />
          </div>
        ))}
      </div>
      {preview && (
        <p className="mt-4 text-sm text-fg2">
          Would flag{" "}
          <span className="font-semibold" style={{ color: "var(--junk)" }}>
            {preview.junk} junk
          </span>{" "}
          +{" "}
          <span className="font-semibold" style={{ color: "var(--borderline)" }}>
            {preview.borderline} borderline
          </span>{" "}
          of {preview.total} titles.
        </p>
      )}
      <button
        onClick={() => api.saveThresholds(thr).then(() => setSaved(true))}
        className="gradient-fill mt-4 rounded-md px-4 py-2 text-sm font-bold shadow-glow"
      >
        {saved ? "Saved ✓" : "Save & re-score"}
      </button>
    </Section>
  );
}

function Autonomy() {
  const tiers = [
    { name: "Add / monitor", policy: "Automatic", tone: "keep" as const, locked: false },
    { name: "Unmonitor", policy: "Automatic + audit", tone: "borderline" as const, locked: false },
    { name: "File delete", policy: "Approval required", tone: "junk" as const, locked: true },
  ];
  return (
    <Section title="Autonomy tiers">
      <div className="divide-y divide-line">
        {tiers.map((t) => (
          <div key={t.name} className="flex items-center gap-3 py-3">
            <span className="flex-1 text-sm font-semibold">{t.name}</span>
            <Pill tone={t.tone}>{t.policy}</Pill>
            {t.locked && <LockIcon size={15} className="text-fg3" />}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-fg3">
        A file delete is always approval-gated and cannot be disabled.
      </p>
    </Section>
  );
}
