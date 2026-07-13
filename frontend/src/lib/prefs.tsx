// Appearance preferences (theme / density / reduce-motion / accent), persisted to
// localStorage and reflected onto <html> data-* attributes that tokens.css reads.

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Theme = "dark" | "light" | "neon";
export type Density = "comfortable" | "compact";

const THEMES: Theme[] = ["dark", "light", "neon"];

interface Prefs {
  theme: Theme;
  density: Density;
  reduceMotion: boolean;
  accent: string | null;
  cycleTheme: () => void;
  setTheme: (t: Theme) => void;
  toggleDensity: () => void;
  setReduceMotion: (v: boolean) => void;
  setAccent: (hex: string | null) => void;
}

const PrefsContext = createContext<Prefs | null>(null);

function read<T extends string>(key: string, fallback: T): T {
  return (localStorage.getItem(key) as T) ?? fallback;
}

// Sift derives a matching duotone from a chosen accent via a +58° hue shift.
function hexToHsl(hex: string): [number, number, number] | null {
  const m = /^#?([\da-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  const r = (n >> 16) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return [h, s * 100, l * 100];
}

function deriveDuotone(hex: string): { accent: string; accent2: string; grad: string } | null {
  const hsl = hexToHsl(hex);
  if (!hsl) return null;
  const [h, s, l] = hsl;
  const accent = `hsl(${h} ${s}% ${l}%)`;
  const accent2 = `hsl(${(h + 58) % 360} ${s}% ${l}%)`;
  const mid = `hsl(${(h + 29) % 360} ${s}% ${Math.min(l + 6, 72)}%)`;
  return { accent, accent2, grad: `linear-gradient(120deg, ${accent}, ${mid} 52%, ${accent2})` };
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => read<Theme>("sift.theme", "dark"));
  const [density, setDensity] = useState<Density>(() =>
    read<Density>("sift.density", "comfortable"),
  );
  const [reduceMotion, setReduceMotionState] = useState<boolean>(
    () => localStorage.getItem("sift.reduceMotion") === "true",
  );
  const [accent, setAccentState] = useState<string | null>(
    () => localStorage.getItem("sift.accent"),
  );

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.density = density;
    root.dataset.reduceMotion = String(reduceMotion);
    localStorage.setItem("sift.theme", theme);
    localStorage.setItem("sift.density", density);
    localStorage.setItem("sift.reduceMotion", String(reduceMotion));
  }, [theme, density, reduceMotion]);

  useEffect(() => {
    const root = document.documentElement;
    if (accent) {
      const d = deriveDuotone(accent);
      if (d) {
        root.style.setProperty("--accent", d.accent);
        root.style.setProperty("--accent2", d.accent2);
        root.style.setProperty("--grad", d.grad);
      }
      localStorage.setItem("sift.accent", accent);
    } else {
      root.style.removeProperty("--accent");
      root.style.removeProperty("--accent2");
      root.style.removeProperty("--grad");
      localStorage.removeItem("sift.accent");
    }
  }, [accent]);

  const value = useMemo<Prefs>(
    () => ({
      theme,
      density,
      reduceMotion,
      accent,
      setTheme: setThemeState,
      cycleTheme: () => setThemeState((t) => THEMES[(THEMES.indexOf(t) + 1) % THEMES.length]),
      toggleDensity: () =>
        setDensity((d) => (d === "comfortable" ? "compact" : "comfortable")),
      setReduceMotion: setReduceMotionState,
      setAccent: setAccentState,
    }),
    [theme, density, reduceMotion, accent],
  );

  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): Prefs {
  const ctx = useContext(PrefsContext);
  if (!ctx) throw new Error("usePrefs must be used within PrefsProvider");
  return ctx;
}

// Convenience: are ambient animations allowed right now?
export function useMotionAllowed(): boolean {
  const { reduceMotion } = usePrefs();
  const [osReduce] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
  );
  return !reduceMotion && !osReduce;
}
