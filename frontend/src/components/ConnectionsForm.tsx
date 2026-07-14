// Reusable connection editor. Renders per-service fields with a Test button and a
// single Save. Used by the Setup Wizard and the Settings page. Secrets already saved
// show a "saved" placeholder — leave blank to keep them, type to replace.

import { useState } from "react";

import { api } from "@/lib/api";
import type { Connections, ServiceHealth } from "@/lib/types";

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
    hint: "Optional — must be reachable from the Sift server, so use a public URL/tunnel (not localhost) when hosted.",
    fields: [
      { name: "base_url", label: "URL", placeholder: "http://your-host:11434 (not localhost)" },
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
  saveLabel = "Save connections",
}: {
  specs?: ServiceSpec[];
  initial: Connections;
  onSaved?: (c: Connections) => void;
  saveLabel?: string;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [tests, setTests] = useState<Record<string, ServiceHealth | "testing">>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(svc: string, field: string, v: string) {
    setVals((p) => ({ ...p, [`${svc}.${field}`]: v }));
    setSaved(false);
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
    try {
      const res = await api.testConfig(spec.key, serviceValues(spec));
      setTests((t) => ({ ...t, [spec.key]: res }));
    } catch {
      setTests((t) => ({
        ...t,
        [spec.key]: { service: spec.key, ok: false, detail: "test failed", latency_ms: null },
      }));
    }
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const connections: Record<string, Record<string, unknown>> = {};
      for (const spec of specs) connections[spec.key] = serviceValues(spec);
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

  return (
    <div className="flex flex-col gap-4">
      {specs.map((spec) => {
        const t = tests[spec.key];
        return (
          <div key={spec.key} className="panel p-4">
            <div className="flex items-center justify-between gap-2">
              <div>
                <span className="font-display text-sm font-bold">{spec.label}</span>
                {spec.hint && <p className="text-xs text-fg3">{spec.hint}</p>}
              </div>
              <button
                onClick={() => test(spec)}
                disabled={t === "testing"}
                className="rounded-pill border border-line px-3 py-1 text-xs font-semibold text-fg2 hover:bg-bg2 disabled:opacity-60"
              >
                {t === "testing" ? "Testing…" : "Test"}
              </button>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {spec.fields.map((f) => {
                const savedFlag = Boolean(initial[spec.key]?.[`${f.name}_set`]);
                return (
                  <label key={f.name} className="text-xs text-fg3">
                    {f.label}
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
