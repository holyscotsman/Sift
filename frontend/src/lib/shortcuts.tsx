// Keyboard navigation: `g` then a letter jumps between pages; `?` toggles a
// shortcuts overlay. Everything is suppressed while typing in a field or while
// a dialog (movie drawer, confirm modal) is open, so chords can't fire "behind"
// a focused surface. `/` (search) is owned by GlobalSearch and listed here only.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const ROUTES: { key: string; to: string; label: string }[] = [
  { key: "d", to: "/", label: "Dashboard" },
  { key: "l", to: "/library", label: "Library" },
  { key: "m", to: "/missing", label: "Missing" },
  { key: "j", to: "/junk", label: "Junk" },
  { key: "a", to: "/ask", label: "Ask" },
  { key: "t", to: "/profile", label: "Taste Profile" },
  { key: "s", to: "/settings", label: "Settings" },
];

function suppressed(): boolean {
  const el = document.activeElement;
  const typing =
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement ||
    (el instanceof HTMLElement && el.isContentEditable);
  return typing || document.querySelector('[role="dialog"]') !== null;
}

export function Shortcuts() {
  const [help, setHelp] = useState(false);
  const chordTimer = useRef<number | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") {
        setHelp(false);
        return;
      }
      if (suppressed()) return;
      if (e.key === "?") {
        e.preventDefault();
        setHelp((h) => !h);
        return;
      }
      if (e.key === "g") {
        // Arm the chord; it decays so a stray `g` doesn't lie in wait forever.
        if (chordTimer.current) window.clearTimeout(chordTimer.current);
        chordTimer.current = window.setTimeout(() => {
          chordTimer.current = null;
        }, 1500);
        return;
      }
      if (chordTimer.current) {
        const hit = ROUTES.find((r) => r.key === e.key);
        if (hit) {
          e.preventDefault();
          navigate(hit.to);
          setHelp(false);
        }
        window.clearTimeout(chordTimer.current);
        chordTimer.current = null;
      }
    };
    // The header menu can open the overlay too (no keyboard needed).
    const onOpen = () => setHelp(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("sift:shortcuts", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("sift:shortcuts", onOpen);
      if (chordTimer.current) window.clearTimeout(chordTimer.current);
    };
  }, [navigate]);

  if (!help) return null;
  return (
    <div
      className="fixed inset-0 z-[95] grid place-items-center bg-black/40 p-4"
      onClick={() => setHelp(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        onClick={(e) => e.stopPropagation()}
        className="panel w-full max-w-sm p-5"
      >
        <div className="flex items-center justify-between">
          <span className="eyebrow">Keyboard shortcuts</span>
          <button onClick={() => setHelp(false)} className="text-fg3 hover:text-fg" aria-label="Close">
            ✕
          </button>
        </div>
        <ul className="mt-3 flex flex-col gap-1.5 text-sm">
          <ShortcutRow keys="/" label="Focus search" />
          {ROUTES.map((r) => (
            <ShortcutRow key={r.key} keys={`g ${r.key}`} label={`Go to ${r.label}`} />
          ))}
          <ShortcutRow keys="Esc" label="Close drawer / dialogs" />
          <ShortcutRow keys="?" label="Toggle this help" />
        </ul>
      </div>
    </div>
  );
}

function ShortcutRow({ keys, label }: { keys: string; label: string }) {
  return (
    <li className="flex items-center justify-between gap-4">
      <span className="text-fg2">{label}</span>
      <kbd className="rounded-md border border-line bg-bg2 px-2 py-0.5 font-mono text-xs text-fg">
        {keys}
      </kbd>
    </li>
  );
}
