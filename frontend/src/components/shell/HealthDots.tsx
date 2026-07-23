// Connection-health dots for Plex / Radarr / Tautulli / TMDB / Model.
// green=ok, amber=warn, red=offline, grey=not configured. Hover shows detail.

import { Link } from "react-router-dom";

import { useHealth } from "@/lib/hooks";
import type { ServiceHealth } from "@/lib/types";

const LABELS: Record<string, string> = {
  plex: "Plex",
  radarr: "Radarr",
  tautulli: "Tautulli",
  tmdb: "TMDB",
  model: "Model",
};

function dotColor(s: ServiceHealth | undefined): string {
  if (!s) return "var(--fg-3)";
  if (s.ok) return "var(--keep)";
  const detail = (s.detail || "").toLowerCase();
  if (detail.includes("disabled") || detail.includes("not configured")) return "var(--fg-3)";
  if (detail.includes("auth")) return "var(--borderline)";
  return "var(--junk)";
}

export function HealthDots() {
  const { data } = useHealth();
  const byName = new Map((data?.services ?? []).map((s) => [s.service, s]));
  // Model is the AI provider surface (Phase 2) — shown as not-configured for now.
  const order = ["plex", "radarr", "tautulli", "tmdb", "model"];

  return (
    // A red dot should lead to the fix, not just diagnose — the group opens
    // Settings › Connections.
    <Link
      to="/settings"
      title="Connection health — open Settings"
      aria-label="Connection health — open settings"
      className="flex items-center gap-1.5 rounded-pill px-1.5 py-1 hover:bg-bg2"
    >
      {order.map((name) => {
        const s = byName.get(name);
        const title = s
          ? `${LABELS[name]}: ${s.ok ? "ok" : "offline"}${s.detail ? ` — ${s.detail}` : ""}${
              s.latency_ms != null ? ` (${s.latency_ms}ms)` : ""
            }`
          : `${LABELS[name]}: not configured`;
        return (
          <span
            key={name}
            title={title}
            aria-label={title}
            className="h-2 w-2 rounded-pill transition-transform hover:scale-125"
            style={{ background: dotColor(s), boxShadow: `0 0 6px ${dotColor(s)}` }}
          />
        );
      })}
    </Link>
  );
}
