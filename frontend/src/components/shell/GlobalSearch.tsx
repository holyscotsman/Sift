// Global jump-to-movie search. `/` focuses it anywhere; Arrow keys move the
// highlight; Enter opens the result; Escape closes. Queries the real /api/movies.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { SearchIcon } from "@/components/icons";
import { api } from "@/lib/api";
import type { Movie } from "@/lib/types";

export function GlobalSearch() {
  const [value, setValue] = useState("");
  const [results, setResults] = useState<Movie[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // `/` focuses search from anywhere (unless already typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Debounced query against the snapshot.
  useEffect(() => {
    if (value.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .movies({ q: value.trim(), page_size: 6 })
        .then((r) => {
          setResults(r.items);
          setActive(0);
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 180);
    return () => window.clearTimeout(t);
  }, [value]);

  function openResult(m: Movie | undefined) {
    setOpen(false);
    if (m) navigate(`/library?q=${encodeURIComponent(m.title)}`);
    else if (value.trim()) navigate(`/library?q=${encodeURIComponent(value.trim())}`);
  }

  function posterGradient(hue: number): string {
    return `linear-gradient(155deg, hsl(${hue} 44% 32%), hsl(${(hue + 38) % 360} 40% 15%))`;
  }

  return (
    <div className="relative w-full max-w-[400px]">
      <div className="flex items-center gap-2 rounded-pill border border-line bg-bg2 px-3 py-1.5">
        <SearchIcon size={15} className="text-fg3 shrink-0" />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onFocus={() => value.trim().length >= 2 && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              openResult(results[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
              inputRef.current?.blur();
            }
          }}
          placeholder="Search library…  (press /)"
          className="w-full bg-transparent text-sm text-fg placeholder:text-fg3 focus:outline-none"
          aria-label="Search library"
        />
      </div>
      {open && results.length > 0 && (
        <ul
          className="glass absolute left-0 right-0 top-[calc(100%+8px)] z-50 overflow-hidden rounded-lg p-1.5 shadow-s2"
          role="listbox"
        >
          {results.map((m, i) => (
            <li key={m.tmdb_id}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => openResult(m)}
                className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left"
                style={{ background: i === active ? "var(--bg-2)" : "transparent" }}
                role="option"
                aria-selected={i === active}
              >
                <span
                  className="h-8 w-6 shrink-0 rounded-sm"
                  style={{ background: posterGradient((m.tmdb_id * 47) % 360) }}
                />
                <span className="truncate text-sm text-fg">{m.title}</span>
                {m.year && <span className="ml-auto text-xs text-fg3">{m.year}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
