// Connection-health dots for Plex / Radarr / Tautulli / TMDB / Model.
//
// **Shape carries the state as well as colour.** Six 8px dots that differ only in
// hue are six identical dots to a colour-blind reader, and this project's own
// standard is glyphs rather than colour alone. The `title`/`aria-label` on each
// one covers screen readers and hovering, but somebody scanning the header with
// a mouse nowhere near it gets nothing — and the whole point of the row is to be
// glanceable.
//
// So: a filled circle is fine, a filled square is broken, a hollow circle is not
// configured. Shape is legible at 8px where a glyph is not, and the three read
// apart in greyscale.

import { Link } from "react-router-dom";

import { useHealth } from "@/lib/hooks";
import type { ServiceHealth } from "@/lib/types";

const LABELS: Record<string, string> = {
  plex: "Plex",
  radarr: "Radarr",
  overseerr: "Overseerr",
  tautulli: "Tautulli",
  tmdb: "TMDB",
  model: "Model",
};

type DotState = "ok" | "warn" | "down" | "off";

function dotState(s: ServiceHealth | undefined): DotState {
  if (!s) return "off";
  if (s.ok) return "ok";
  const detail = (s.detail || "").toLowerCase();
  if (detail.includes("disabled") || detail.includes("not configured")) return "off";
  if (detail.includes("auth")) return "warn";
  return "down";
}

const DOT_COLOR: Record<DotState, string> = {
  ok: "var(--keep)",
  warn: "var(--borderline)",
  down: "var(--junk)",
  off: "var(--fg-3)",
};

// Radius doubles as the shape cue: fully round for healthy, barely rounded for
// broken. `warn` stays square-ish too — it is a problem, and it should not read
// as fine to anyone who cannot see the amber.
const DOT_RADIUS: Record<DotState, string> = {
  ok: "9999px",
  warn: "2px",
  down: "1px",
  off: "9999px",
};

export function HealthDots() {
  const { data } = useHealth();
  const byName = new Map((data?.services ?? []).map((s) => [s.service, s]));
  // Model is the AI provider surface (Phase 2) — shown as not-configured for now.
  const order = ["plex", "radarr", "overseerr", "tautulli", "tmdb", "model"];

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
        const state = dotState(s);
        const color = DOT_COLOR[state];
        return (
          <span
            key={name}
            title={title}
            aria-label={title}
            className="h-2 w-2 transition-transform hover:scale-125"
            style={{
              // "off" is hollow: nothing is wrong, nothing is connected either,
              // and an empty outline says that without needing to be grey.
              background: state === "off" ? "transparent" : color,
              border: state === "off" ? `1.5px solid ${color}` : undefined,
              borderRadius: DOT_RADIUS[state],
              boxShadow: state === "off" ? "none" : `0 0 6px ${color}`,
            }}
          />
        );
      })}
    </Link>
  );
}
