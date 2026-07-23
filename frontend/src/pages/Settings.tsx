// Settings — appearance (theme/accent/density/motion), connection status with test,
// scoring thresholds with live "would flag N" preview, and the autonomy tiers.

import { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmModal } from "@/components/ConfirmModal";
import { ConnectionsForm } from "@/components/ConnectionsForm";
import { LockIcon } from "@/components/icons";
import { Pill } from "@/components/ui";
import { api, setToken } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import type { Connections as ConnConfig, ServiceHealth, ThresholdPreview, Thresholds } from "@/lib/types";

const TABS = ["Appearance", "Connections", "Scoring", "Autonomy", "Account"] as const;
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
          {tab === "Account" && <Account />}
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
  const [config, setConfig] = useState<ConnConfig | null>(null);

  const refreshStatus = useCallback(() => {
    api.getSettings().then((s) => setRows(s.connections)).catch(() => setRows([]));
  }, []);

  useEffect(() => {
    refreshStatus();
    api.getConfig().then((c) => setConfig(c.connections)).catch(() => setConfig({}));
  }, [refreshStatus]);

  return (
    <>
      <Section title="Status">
        <div className="divide-y divide-line">
          {rows.map((r) => {
            // "Never set up" is a neutral state, not a failure — only a service
            // that IS configured but can't be reached deserves the red dot.
            const notConfigured = !r.ok && ["disabled", "not configured"].includes(r.detail);
            return (
              <div key={r.service} className="flex items-center gap-3 py-2.5">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{
                    background: r.ok
                      ? "var(--keep)"
                      : notConfigured
                        ? "var(--fg-3)"
                        : "var(--junk)",
                  }}
                />
                <span className="w-24 text-sm font-semibold capitalize">{r.service}</span>
                <span
                  className="flex-1 truncate text-xs"
                  style={{ color: !r.ok && !notConfigured ? "var(--junk)" : "var(--fg-3)" }}
                >
                  {notConfigured ? "Not set up — add it below to unlock its features" : r.detail}
                </span>
              </div>
            );
          })}
        </div>
      </Section>
      <span className="eyebrow">Edit connections</span>
      <p className="mb-3 mt-1 text-xs text-fg3">
        Entered here and stored on your server — no need to touch Render. Test each one, then save.
      </p>
      {config === null ? (
        <div className="panel p-5 text-sm text-fg3">Loading…</div>
      ) : (
        <ConnectionsForm
          initial={config}
          onSaved={(c) => {
            setConfig(c);
            refreshStatus();
          }}
        />
      )}
    </>
  );
}

function Account() {
  const [username, setUsername] = useState<string | null>(null);
  const [modal, setModal] = useState<null | { keepThumbs: boolean }>(null);
  const [busy, setBusy] = useState(false);
  const [ephemeral, setEphemeral] = useState(false);

  useEffect(() => {
    api.authStatus().then((s) => setUsername(s.username)).catch(() => setUsername(null));
    api.getSettings().then((s) => setEphemeral(s.ephemeral_risk)).catch(() => {});
  }, []);

  async function doReset(keepThumbs: boolean) {
    setBusy(true);
    try {
      await api.resetInstance(keepThumbs);
      setToken(null);
      window.location.reload(); // back to the setup wizard
    } finally {
      setBusy(false);
      setModal(null);
    }
  }

  return (
    <>
      {ephemeral && (
        <div
          className="mb-4 rounded-lg border p-4 text-sm"
          style={{ borderColor: "var(--borderline)", color: "var(--borderline)" }}
        >
          <strong>Your login and settings reset on redeploy.</strong> This instance runs
          on SQLite on a host with an ephemeral disk. Connect a free Postgres (set
          <code className="mx-1 rounded bg-bg2 px-1">SIFT_DATABASE__URL</code>, see
          docs/DEPLOY.md) and everything — login included — survives.
        </div>
      )}

      <Section title="Account">
        <p className="text-sm text-fg2">
          Signed in as <span className="font-semibold text-fg">{username ?? "—"}</span>.
        </p>
        <button
          onClick={() => {
            setToken(null);
            window.location.reload();
          }}
          className="mt-3 rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
        >
          Sign out
        </button>
      </Section>

      <PasswordSection />
      <StorageSection />

      <Section title="Reset">
        <p className="text-sm text-fg2">
          Wipe the library snapshot, saved connections, and your login, returning Sift to the setup
          wizard. This cannot be undone.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => setModal({ keepThumbs: true })}
            className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2"
          >
            Reset · keep thumbnails
          </button>
          <button
            onClick={() => setModal({ keepThumbs: false })}
            className="rounded-md px-4 py-2 text-sm font-bold"
            style={{ background: "var(--junk)", color: "var(--accent-fg)" }}
          >
            Reset everything
          </button>
        </div>
        <p className="mt-2 text-xs text-fg3">
          “Keep thumbnails” preserves the poster cache so your next scan renders instantly.
        </p>
      </Section>

      <ConfirmModal
        open={modal !== null}
        title={modal?.keepThumbs ? "Reset (keep thumbnails)?" : "Reset everything?"}
        confirmLabel={busy ? "Resetting…" : "Reset"}
        busy={busy}
        onCancel={() => setModal(null)}
        onConfirm={() => modal && doReset(modal.keepThumbs)}
        body={
          <p className="text-sm text-fg2">
            This wipes your library snapshot, saved connections, and login
            {modal?.keepThumbs ? " but keeps the thumbnail cache" : " and clears the thumbnail cache"}.
            You'll be taken back to the setup wizard.
          </p>
        }
      />
    </>
  );
}

// Automatic rescans: keeps the snapshot fresh without remembering to click Run
// scan. The backend anchors to the last completed scan, never double-runs.
const RESCAN_CHOICES = [
  { hours: 0, label: "Off" },
  { hours: 6, label: "Every 6h" },
  { hours: 12, label: "Every 12h" },
  { hours: 24, label: "Daily" },
];

function RescanSection() {
  const [interval, setIntervalHours] = useState<number | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => setIntervalHours(s.scan_interval_hours)).catch(() => {});
  }, []);

  async function choose(hours: number) {
    const prev = interval;
    setIntervalHours(hours);
    try {
      await api.saveScanSchedule(hours);
    } catch {
      setIntervalHours(prev);
    }
  }

  return (
    <Section title="Automatic rescan">
      <p className="text-sm text-fg2">
        Refresh the snapshot on a schedule. A rescan only starts when no scan is already
        running and Plex is connected.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {RESCAN_CHOICES.map((c) => (
          <button
            key={c.hours}
            onClick={() => void choose(c.hours)}
            disabled={interval === null}
            className={`rounded-pill border px-3 py-1.5 text-xs font-semibold ${
              interval === c.hours
                ? "border-accent-line bg-accent-soft text-accent"
                : "border-line text-fg2 hover:bg-bg2"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
    </Section>
  );
}

// Change the password in place — no more factory reset just to rotate it.
// Existing sessions (including this one) stay signed in.
function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<null | { ok: boolean; text: string }>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (next.length < 8) return setMsg({ ok: false, text: "New password needs 8+ characters." });
    if (next !== confirm) return setMsg({ ok: false, text: "New passwords don't match." });
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setMsg({ ok: true, text: "Password changed. Your sessions stay signed in." });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setMsg({
        ok: false,
        text: err instanceof Error && err.message ? err.message : "Couldn't change the password.",
      });
    } finally {
      setBusy(false);
    }
  }

  const field =
    "mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]";
  return (
    <Section title="Password">
      <form onSubmit={submit} className="grid max-w-md grid-cols-1 gap-3">
        <label className="text-xs text-fg3">
          Current password
          <input
            type="password"
            name="current-password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={field}
          />
        </label>
        <label className="text-xs text-fg3">
          New password (8+ characters)
          <input
            type="password"
            name="new-password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={field}
          />
        </label>
        <label className="text-xs text-fg3">
          Confirm new password
          <input
            type="password"
            name="confirm-new-password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={field}
          />
        </label>
        {msg && (
          <p className="text-sm" style={{ color: msg.ok ? "var(--keep)" : "var(--junk)" }}>
            {msg.text}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !current || !next}
          className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
        >
          {busy ? "Changing…" : "Change password"}
        </button>
      </form>
    </Section>
  );
}

// Poster-cache footprint + a clear button; the cache refills on demand.
function StorageSection() {
  const [stats, setStats] = useState<null | { count: number; bytes: number }>(null);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(() => {
    api.posterStats().then(setStats).catch(() => setStats(null));
  }, []);
  useEffect(load, [load]);

  async function clear() {
    setClearing(true);
    try {
      await api.clearPosterCache();
      load();
    } finally {
      setClearing(false);
    }
  }

  const mb = stats ? (stats.bytes / 1e6).toFixed(0) : "—";
  return (
    <Section title="Storage">
      <div className="flex flex-wrap items-center gap-3 text-sm text-fg2">
        <span>
          Poster cache:{" "}
          <span className="font-semibold text-fg">
            {stats ? `${stats.count} file(s) · ${mb} MB` : "—"}
          </span>
        </span>
        <button
          onClick={clear}
          disabled={clearing || !stats || stats.count === 0}
          className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
        >
          {clearing ? "Clearing…" : "Clear"}
        </button>
      </div>
      <p className="mt-2 text-xs text-fg3">
        Clearing never touches your library data — posters re-download as they're viewed.
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
  const [dryRun, setDryRun] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getActionsConfig().then((a) => setDryRun(a.dry_run)).catch(() => setDryRun(null));
  }, []);

  async function toggle(next: boolean) {
    setSaving(true);
    try {
      const res = await api.setActionsConfig(next);
      setDryRun(res.dry_run);
    } finally {
      setSaving(false);
    }
  }

  const tiers = [
    { name: "Add / monitor", policy: "Automatic", tone: "keep" as const, locked: false },
    { name: "Unmonitor", policy: "Automatic + audit", tone: "borderline" as const, locked: false },
    { name: "File delete", policy: "Approval required", tone: "junk" as const, locked: true },
  ];

  return (
    <>
      <Section title="Write mode">
        <p className="text-sm text-fg2">
          Controls whether approved actions are actually sent to Radarr, or only staged
          (logged, nothing sent). File deletes still require per-item approval either way.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => toggle(true)}
            disabled={saving || dryRun === null}
            className={`rounded-md border px-4 py-2 text-sm font-semibold ${
              dryRun ? "border-accent-line text-accent" : "border-line text-fg2 hover:bg-bg2"
            }`}
          >
            Staged (dry-run)
          </button>
          <button
            onClick={() => toggle(false)}
            disabled={saving || dryRun === null}
            className={`rounded-md border px-4 py-2 text-sm font-semibold ${
              dryRun === false ? "border-accent-line text-accent" : "border-line text-fg2 hover:bg-bg2"
            }`}
          >
            Live — send to Radarr
          </button>
        </div>
        {dryRun === false && (
          <p className="mt-2 text-xs" style={{ color: "var(--junk)" }}>
            Live mode: approving a removal will delete the file in Radarr. This can't be undone.
          </p>
        )}
        {dryRun === null && <p className="mt-2 text-xs text-fg3">Loading…</p>}
      </Section>

      <RescanSection />

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
    </>
  );
}
