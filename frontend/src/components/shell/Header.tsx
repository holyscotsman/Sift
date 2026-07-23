// Floating frosted header: wordmark · global search · health dots · the app
// menu (row spacing, theme, shortcuts, sign out) · scan status pill · the one
// gradient "Run scan" CTA.

import { useEffect, useRef, useState } from "react";

import { DensityIcon, PlaneIcon, ScanIcon, SunIcon } from "@/components/icons";
import { setToken } from "@/lib/api";
import { usePrefs } from "@/lib/prefs";
import { useScan } from "@/lib/scan";

import { GlobalSearch } from "./GlobalSearch";
import { HealthDots } from "./HealthDots";

const THEME_LABEL: Record<string, string> = { dark: "Dark", light: "Light", neon: "Neon" };

// The three-line button used to silently toggle row density — it now opens a
// real menu so every control behind it is discoverable.
function AppMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { theme, cycleTheme, density, toggleDensity } = usePrefs();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const item =
    "flex w-full items-center justify-between gap-4 rounded-md px-3 py-2 text-left text-sm text-fg2 hover:bg-bg2 hover:text-fg";
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Menu"
        title="Menu"
        className="grid h-8 w-8 place-items-center rounded-md text-fg2 hover:bg-bg2"
      >
        <DensityIcon size={16} />
      </button>
      {open && (
        <div
          role="menu"
          className="glass absolute right-0 top-[calc(100%+8px)] z-50 w-56 rounded-lg p-1.5 shadow-s2"
        >
          <button role="menuitem" className={item} onClick={toggleDensity}>
            Row spacing
            <span className="text-xs capitalize text-fg3">{density}</span>
          </button>
          <button role="menuitem" className={item} onClick={cycleTheme}>
            Theme
            <span className="text-xs text-fg3">{THEME_LABEL[theme]}</span>
          </button>
          <button
            role="menuitem"
            className={item}
            onClick={() => {
              setOpen(false);
              window.dispatchEvent(new Event("sift:shortcuts"));
            }}
          >
            Keyboard shortcuts
            <kbd className="rounded border border-line bg-bg2 px-1.5 font-mono text-[11px]">?</kbd>
          </button>
          <a
            role="menuitem"
            className={item}
            href="https://github.com/holyscotsman/Sift/blob/main/CHANGELOG.md"
            target="_blank"
            rel="noreferrer"
            onClick={() => setOpen(false)}
          >
            Changelog
          </a>
          <div className="my-1 border-t border-line" />
          <button
            role="menuitem"
            className={item}
            onClick={() => {
              setToken(null);
              window.dispatchEvent(new Event("sift:unauthorized"));
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Header() {
  const { theme, cycleTheme } = usePrefs();
  const { scanning, pct, start, setPanelOpen } = useScan();

  return (
    // On phones the search gets its own full-width row below the controls
    // (there's no room beside the logo); ≥md it sits centered in the bar.
    <header className="glass flex min-h-[60px] flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3 py-2 md:h-[60px] md:flex-nowrap md:py-0">
      <a href="/" className="group flex items-center gap-2.5 pl-1 pr-2" aria-label="Sift home">
        <span
          className="grid h-8 w-8 place-items-center rounded-lg text-[color:var(--accent-fg)] shadow-glow transition-transform group-hover:scale-105"
          style={{ background: "var(--grad)" }}
        >
          <PlaneIcon size={17} />
        </span>
        <span className="gradient-text font-display text-[22px] font-extrabold leading-none tracking-tight">
          Sift
        </span>
      </a>

      <div className="order-last w-full md:order-none md:ml-1 md:flex md:w-auto md:flex-1 md:justify-center">
        <GlobalSearch />
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="hidden lg:block">
          <HealthDots />
        </div>

        <button
          onClick={cycleTheme}
          title={`Theme: ${THEME_LABEL[theme]}`}
          aria-label={`Theme: ${THEME_LABEL[theme]}`}
          className="grid h-8 w-8 place-items-center rounded-md text-fg2 hover:bg-bg2"
        >
          <SunIcon size={16} />
        </button>
        <AppMenu />

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
          className="gradient-fill flex items-center gap-1.5 whitespace-nowrap rounded-pill px-4 py-1.5 text-xs font-bold shadow-glow disabled:opacity-60"
        >
          <ScanIcon size={15} />
          Run scan
        </button>
      </div>
    </header>
  );
}
