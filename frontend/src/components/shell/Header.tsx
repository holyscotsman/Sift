// Floating frosted header: wordmark · global search · health dots · density /
// theme toggles · scan status pill · the one gradient "Run scan" CTA.

import { DensityIcon, PlaneIcon, ScanIcon, SunIcon } from "@/components/icons";
import { usePrefs } from "@/lib/prefs";
import { useScan } from "@/lib/scan";

import { GlobalSearch } from "./GlobalSearch";
import { HealthDots } from "./HealthDots";

const THEME_LABEL: Record<string, string> = { dark: "Dark", light: "Light", neon: "Neon" };

export function Header() {
  const { theme, cycleTheme, density, toggleDensity } = usePrefs();
  const { scanning, pct, start, setPanelOpen } = useScan();

  return (
    <header className="glass flex h-[60px] items-center gap-3 rounded-xl px-3">
      <a href="/" className="flex items-center gap-2 pl-1 pr-2" aria-label="Sift home">
        <span
          className="grid h-7 w-7 place-items-center rounded-md text-[color:var(--accent-fg)]"
          style={{ background: "var(--grad)" }}
        >
          <PlaneIcon size={15} />
        </span>
        <span className="gradient-text font-display text-[17px] font-extrabold tracking-tight">
          Sift
        </span>
      </a>

      <div className="ml-1 hidden flex-1 justify-center md:flex">
        <GlobalSearch />
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="hidden lg:block">
          <HealthDots />
        </div>

        <button
          onClick={toggleDensity}
          title={`Row spacing: ${density} — switch to ${
            density === "comfortable" ? "compact" : "comfortable"
          }`}
          aria-label={`Row spacing: ${density}. Switch to ${
            density === "comfortable" ? "compact" : "comfortable"
          }`}
          className="grid h-8 w-8 place-items-center rounded-md text-fg2 hover:bg-bg2"
        >
          <DensityIcon size={16} />
        </button>
        <button
          onClick={cycleTheme}
          title={`Theme: ${THEME_LABEL[theme]}`}
          aria-label={`Theme: ${THEME_LABEL[theme]}`}
          className="grid h-8 w-8 place-items-center rounded-md text-fg2 hover:bg-bg2"
        >
          <SunIcon size={16} />
        </button>

        <button
          onClick={() => setPanelOpen(true)}
          className="rounded-pill border border-line px-3 py-1.5 text-xs font-semibold text-fg2 hover:bg-bg2"
        >
          {scanning ? (
            <span className="flex items-center gap-1.5">
              <span
                className="h-1.5 w-1.5 rounded-pill bg-accent"
                style={{ animation: "sift-pulse 1s infinite", animationPlayState: "var(--anim)" }}
              />
              Scanning {pct}%
            </span>
          ) : (
            "Idle"
          )}
        </button>

        <button
          onClick={() => void start()}
          disabled={scanning}
          className="gradient-fill flex items-center gap-1.5 rounded-pill px-4 py-1.5 text-xs font-bold shadow-glow disabled:opacity-60"
        >
          <ScanIcon size={15} />
          Run scan
        </button>
      </div>
    </header>
  );
}
