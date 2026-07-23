// Floating scan panel: a sweeping radar, a 0–100% counter, and the phase
// checklist. Opens on scan; auto-closes shortly after completion.

import { CheckIcon } from "@/components/icons";
import { useMotionAllowed } from "@/lib/prefs";
import { SCAN_PHASES, useScan } from "@/lib/scan";

export function ScanPanel() {
  const { panelOpen, scanning, pct, phaseStates, error, setPanelOpen, start } = useScan();
  const motion = useMotionAllowed();
  if (!panelOpen) return null;

  return (
    <div
      className="panel fixed right-4 top-[92px] z-40 w-[312px] p-4 page-enter"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center justify-between">
        <span className="eyebrow">{scanning ? "Scanning library" : error ? "Scan failed" : "Scan complete"}</span>
        <button
          onClick={() => setPanelOpen(false)}
          className="text-fg3 hover:text-fg"
          aria-label="Close scan panel"
        >
          ✕
        </button>
      </div>

      <div className="my-3 flex items-center gap-4">
        <div
          className="relative grid h-16 w-16 place-items-center rounded-full"
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        >
          <div
            className="absolute inset-1 rounded-full"
            style={{
              background: `conic-gradient(from 0deg, transparent, var(--accent-soft), var(--accent))`,
              animation: motion && scanning ? "sift-spin 1.8s linear infinite" : "none",
              animationPlayState: "var(--anim)",
              maskImage: "radial-gradient(transparent 52%, #000 54%)",
              WebkitMaskImage: "radial-gradient(transparent 52%, #000 54%)",
            }}
          />
          <span className="font-display text-lg font-extrabold">{pct}%</span>
        </div>
        <div className="flex-1">
          <div className="h-1.5 overflow-hidden rounded-pill bg-bg2">
            <div
              className="h-full rounded-pill"
              style={{ width: `${pct}%`, background: "var(--grad)", transition: "width .3s" }}
            />
          </div>
          <p className="mt-2 text-xs text-fg3">
            {error ? error : scanning ? "Reading your library…" : "Snapshot updated."}
          </p>
          {/* A failure offers the way forward right here — the server resumes
              from the last completed phase when it can. */}
          {error && !scanning && (
            <button
              onClick={() => void start()}
              className="mt-2 rounded-md border border-line px-3 py-1 text-xs font-semibold text-fg2 hover:bg-bg2"
            >
              Retry scan
            </button>
          )}
        </div>
      </div>

      <ul className="flex flex-col gap-1.5">
        {SCAN_PHASES.map((p) => {
          const st = phaseStates[p.key];
          return (
            <li key={p.key} className="flex items-center gap-2.5 text-[13px]">
              <span
                className="grid h-4 w-4 place-items-center rounded-full"
                style={{
                  background:
                    st === "done" ? "var(--keep)" : st === "active" ? "var(--accent)" : "var(--bg-3)",
                  animation:
                    st === "active" && motion ? "sift-pulse 1s infinite" : "none",
                  animationPlayState: "var(--anim)",
                }}
              >
                {st === "done" && <CheckIcon size={11} className="text-[color:var(--accent-fg)]" />}
              </span>
              <span className={st === "idle" ? "text-fg3" : "text-fg"}>{p.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
