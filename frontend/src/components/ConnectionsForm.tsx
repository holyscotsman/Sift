// Reusable connection editor. Renders per-service fields with a Test button and a
// single Save. Used by the Setup Wizard and the Settings page. Secrets already saved
// show a "saved" placeholder — leave blank to keep them, type to replace.

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { Connections, ServiceHealth } from "@/lib/types";

// AI engine modes: tandem uses both providers (local drafts, Claude refines);
// the other two pin all AI work to a single provider.
const AI_MODES: { value: string; label: string; hint: string }[] = [
  { value: "tandem", label: "Tandem", hint: "Local drafts, Claude refines — best of both." },
  { value: "anthropic", label: "Claude only", hint: "Every AI task goes to Anthropic." },
  { value: "ollama", label: "Local only", hint: "Every AI task stays on your Ollama." },
];

interface FieldSpec {
  name: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
}
export interface ServiceSpec {
  key: string;
  label: string;
  hint?: string;
  fields: FieldSpec[];
}

export const SERVICE_SPECS: ServiceSpec[] = [
  {
    key: "plex",
    label: "Plex",
    hint: "Your library — the source of truth.",
    fields: [
      { name: "base_url", label: "Server URL", placeholder: "http://192.168.1.10:32400" },
      { name: "token", label: "X-Plex-Token", secret: true },
    ],
  },
  {
    key: "radarr",
    label: "Radarr",
    hint: "Management overlay for adds/removals.",
    fields: [
      { name: "base_url", label: "URL", placeholder: "http://host:7878" },
      { name: "api_key", label: "API key", secret: true },
    ],
  },
  {
    key: "tmdb",
    label: "TMDB",
    hint: "Metadata, posters, and discovery.",
    fields: [{ name: "api_key", label: "API key (v3 or v4)", secret: true }],
  },
  {
    key: "tautulli",
    label: "Tautulli",
    hint: "Optional — watch history for engagement scoring.",
    fields: [
      { name: "base_url", label: "URL", placeholder: "http://host:8181" },
      { name: "api_key", label: "API key", secret: true },
    ],
  },
  {
    key: "ollama",
    label: "Local AI (Ollama)",
    hint: "Optional — must be reachable from the Sift server. Quickest: run `cloudflared tunnel --url http://localhost:11434` on the Ollama machine and paste the https URL it prints.",
    fields: [
      { name: "base_url", label: "URL", placeholder: "https://your-tunnel.trycloudflare.com" },
      { name: "model", label: "Model", placeholder: "llama3.1" },
    ],
  },
  {
    key: "anthropic",
    label: "Anthropic (Claude)",
    hint: "Optional — the hard-reasoning pass and Ask.",
    fields: [
      { name: "api_key", label: "API key", secret: true },
      { name: "model", label: "Model", placeholder: "claude-sonnet-5" },
    ],
  },
];

export function ConnectionsForm({
  specs = SERVICE_SPECS,
  initial,
  onSaved,
  onEssentialsReady,
  saveLabel = "Save connections",
}: {
  specs?: ServiceSpec[];
  initial: Connections;
  onSaved?: (c: Connections) => void;
  // Fired once, the moment both Plex and Radarr have tested green — their values are
  // auto-saved so the caller (the wizard) can start the first scan in the background.
  onEssentialsReady?: () => void;
  saveLabel?: string;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, ServiceHealth | "testing">>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiMode, setAiMode] = useState<string>(
    typeof initial.ai?.mode === "string" ? (initial.ai.mode as string) : "tandem",
  );
  const [anthropicModels, setAnthropicModels] = useState<string[]>([]);
  const essentialsFired = useRef(false);
  // Which service's Clear button is in its "Really clear?" confirm step.
  const [confirmClear, setConfirmClear] = useState<string | null>(null);

  useEffect(() => {
    if (confirmClear === null) return;
    const t = window.setTimeout(() => setConfirmClear(null), 4000);
    return () => window.clearTimeout(t);
  }, [confirmClear]);

  function hasSaved(spec: ServiceSpec): boolean {
    const saved = initial[spec.key] ?? {};
    return Object.values(saved).some((v) => v === true || (typeof v === "string" && v !== ""));
  }

  // Empty string means "clear this field" server-side (blank inputs mean "keep",
  // so this is the only way to remove a dead URL or key from the UI).
  async function doClear(spec: ServiceSpec) {
    const blanks = Object.fromEntries(spec.fields.map((f) => [f.name, ""]));
    try {
      const res = await api.saveConfig({ [spec.key]: blanks });
      setVals((p) => {
        const n = { ...p };
        for (const f of spec.fields) delete n[`${spec.key}.${f.name}`];
        return n;
      });
      setTests((t) => {
        const n = { ...t };
        delete n[spec.key];
        return n;
      });
      onSaved?.(res.connections);
    } finally {
      setConfirmClear(null);
    }
  }

  function set(svc: string, field: string, v: string) {
    setVals((p) => ({ ...p, [`${svc}.${field}`]: v }));
    setSaved(false);
  }

  // A hosted Sift can't reach the operator's own machine — the #1 setup gotcha
  // (esp. Ollama). Warn as soon as a URL points at localhost, before Test fails.
  const isHosted = typeof location !== "undefined" && !/^(localhost|127\.|0\.0\.0\.0)/.test(location.hostname);
  function localhostWarning(svc: string, field: string): string | null {
    if (field !== "base_url" || !isHosted) return null;
    const v = (vals[`${svc}.${field}`] ?? "").toLowerCase();
    return /localhost|127\.0\.0\.1|0\.0\.0\.0/.test(v)
      ? "This points at localhost — Sift runs on a server and can't reach your machine. Use a LAN IP or a tunnel URL."
      : null;
  }

  // Collect the entered (non-blank) values for one service. Blank secrets are omitted
  // so a saved key is preserved rather than cleared.
  function serviceValues(spec: ServiceSpec): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of spec.fields) {
      const v = vals[`${spec.key}.${f.name}`];
      if (v !== undefined && v.trim() !== "") out[f.name] = v.trim();
    }
    return out;
  }

  async function test(spec: ServiceSpec) {
    setTests((t) => ({ ...t, [spec.key]: "testing" }));
    let res: ServiceHealth;
    try {
      res = await api.testConfig(spec.key, serviceValues(spec));
    } catch {
      res = { service: spec.key, ok: false, detail: "test failed", latency_ms: null };
    }
    setTests((t) => ({ ...t, [spec.key]: res }));
    if (spec.key === "anthropic" && res.ok && res.models?.length) {
      setAnthropicModels(res.models);
      // Materialise the picker's value so Save persists what the dropdown shows —
      // including when a previously saved model isn't in the fetched list anymore.
      const current = vals["anthropic.model"] || (initial.anthropic?.model as string) || "";
      if (!current || !res.models.includes(current)) {
        set("anthropic", "model", res.models[0]);
      }
    }
  }

  // The moment Plex + Radarr have both tested green, quietly persist everything
  // entered so far and let the wizard kick off the first scan in the background.
  // An effect (not test()'s closure) so it reads fresh state: concurrent Test
  // clicks or edits made while a request was in flight can't lose the trigger.
  useEffect(() => {
    const ok = (key: string) => (tests[key] as ServiceHealth | undefined)?.ok === true;
    if (!onEssentialsReady || essentialsFired.current || !ok("plex") || !ok("radarr")) return;
    essentialsFired.current = true;
    const payload: Record<string, Record<string, unknown>> = {};
    for (const s of specs) {
      const values = serviceValues(s);
      if (Object.keys(values).length > 0) payload[s.key] = values;
    }
    void api
      .saveConfig(payload)
      .then(() => onEssentialsReady())
      .catch(() => {
        essentialsFired.current = false; // let a later test retry
      });
    // vals/specs are read at the commit where tests changed — intentionally not deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tests]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const connections: Record<string, Record<string, unknown>> = {};
      for (const spec of specs) connections[spec.key] = serviceValues(spec);
      connections.ai = { mode: aiMode };
      const res = await api.saveConfig(connections);
      setSaved(true);
      setVals({}); // clear typed secrets; saved state now reflects *_set flags
      onSaved?.(res.connections);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  const hasAi = specs.some((s) => s.key === "ollama" || s.key === "anthropic");

  return (
    <div className="flex flex-col gap-4">
      {specs.map((spec) => {
        const t = tests[spec.key];
        return (
          <div key={spec.key} className="contents">
          {hasAi && spec.key === "ollama" && (
            <div className="panel p-4">
              <span className="font-display text-sm font-bold">AI engine</span>
              <p className="text-xs text-fg3">
                How Sift uses AI. Advisory only — AI never decides what gets removed.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {AI_MODES.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => {
                      setAiMode(m.value);
                      setSaved(false);
                    }}
                    title={m.hint}
                    className={`rounded-pill border px-3 py-1.5 text-xs font-semibold ${
                      aiMode === m.value
                        ? "border-accent-line bg-accent-soft text-accent"
                        : "border-line text-fg2 hover:bg-bg2"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-fg3">
                {AI_MODES.find((m) => m.value === aiMode)?.hint}
              </p>
            </div>
          )}
          <div className="panel p-4">
            <div className="flex items-center justify-between gap-2">
              <div>
                <span className="font-display text-sm font-bold">{spec.label}</span>
                {spec.hint && <p className="text-xs text-fg3">{spec.hint}</p>}
              </div>
              <div className="flex items-center gap-2">
                {hasSaved(spec) &&
                  (confirmClear === spec.key ? (
                    <button
                      onClick={() => void doClear(spec)}
                      className="rounded-pill px-3 py-1 text-xs font-bold"
                      style={{ background: "var(--junk)", color: "var(--accent-fg)" }}
                    >
                      Really clear?
                    </button>
                  ) : (
                    <button
                      onClick={() => setConfirmClear(spec.key)}
                      className="rounded-pill px-3 py-1 text-xs font-semibold text-fg3 hover:text-fg"
                    >
                      Clear saved
                    </button>
                  ))}
                <button
                  onClick={() => test(spec)}
                  disabled={t === "testing"}
                  className="rounded-pill border border-line px-3 py-1 text-xs font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
                >
                  {t === "testing" ? "Testing…" : "Test"}
                </button>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {spec.fields.map((f) => {
                const savedFlag = Boolean(initial[spec.key]?.[`${f.name}_set`]);
                const warn = localhostWarning(spec.key, f.name);
                // Once the Anthropic key is verified, the model becomes a picker
                // over the models that key can actually use.
                const modelPicker =
                  spec.key === "anthropic" && f.name === "model" && anthropicModels.length > 0;
                return (
                  <label key={f.name} className="text-xs text-fg3">
                    {f.label}
                    {modelPicker ? (
                      <select
                        value={
                          vals["anthropic.model"] ||
                          (initial.anthropic?.model as string) ||
                          anthropicModels[0]
                        }
                        onChange={(e) => set("anthropic", "model", e.target.value)}
                        className="mt-1 w-full rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                      >
                        {anthropicModels.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={f.secret ? "password" : "text"}
                        value={vals[`${spec.key}.${f.name}`] ?? ""}
                        onChange={(e) => set(spec.key, f.name, e.target.value)}
                        placeholder={
                          f.secret && savedFlag
                            ? "•••••••• saved (leave blank to keep)"
                            : (initial[spec.key]?.[f.name] as string) || f.placeholder || ""
                        }
                        autoComplete="off"
                        className="mt-1 w-full rounded-md border border-line bg-panel px-2.5 py-1.5 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-[color:var(--accent)]"
                      />
                    )}
                    {warn && (
                      <span className="mt-1 block text-[11px]" style={{ color: "var(--borderline)" }}>
                        {warn}
                      </span>
                    )}
                  </label>
                );
              })}
            </div>
            {t && t !== "testing" && (
              <p
                className="mt-2 text-xs font-semibold"
                style={{ color: t.ok ? "var(--keep)" : "var(--junk)" }}
              >
                {t.ok ? "✓ " : "✕ "}
                {t.detail}
              </p>
            )}
          </div>
          </div>
        );
      })}

      {error && <p className="text-sm" style={{ color: "var(--junk)" }}>{error}</p>}
      <button
        onClick={save}
        disabled={saving}
        className="gradient-fill w-full rounded-md py-2.5 text-sm font-bold shadow-glow disabled:opacity-60"
      >
        {saving ? "Saving…" : saved ? "Saved ✓" : saveLabel}
      </button>
    </div>
  );
}
