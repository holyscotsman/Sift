// Global movie-drawer state: any surface can open the detail drawer for a tmdb id.
//
// Split into two contexts on purpose. Almost every consumer only wants to *open*
// the drawer — a grid tile, a search result, a row in the activity log — and none
// of them care which film is currently showing. Holding both in one context meant
// a new context value on every open and close, and `memo` does not stop a context
// update: every mounted tile re-rendered twice per interaction. Library appends on
// infinite scroll and never trims, so after scrolling a large library that is
// thousands of re-renders for a click that changes one panel.
//
// The actions context is created once and never changes identity. Only the drawer
// itself subscribes to which film is open.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface DrawerActions {
  open: (tmdbId: number) => void;
  close: () => void;
}

const ActionsCtx = createContext<DrawerActions | null>(null);
const TargetCtx = createContext<number | null>(null);

export function DrawerProvider({ children }: { children: ReactNode }) {
  const [movieId, setMovieId] = useState<number | null>(null);

  useEffect(() => {
    if (movieId === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMovieId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [movieId]);

  const close = useCallback(() => setMovieId(null), []);
  // Empty dependency list is the whole point: this object must never be rebuilt,
  // or every consumer re-renders again.
  const actions = useMemo<DrawerActions>(() => ({ open: setMovieId, close }), [close]);

  return (
    <ActionsCtx.Provider value={actions}>
      <TargetCtx.Provider value={movieId}>{children}</TargetCtx.Provider>
    </ActionsCtx.Provider>
  );
}

/** Open or close the drawer. Stable across renders — safe for any list row. */
export function useDrawer(): DrawerActions {
  const ctx = useContext(ActionsCtx);
  if (!ctx) throw new Error("useDrawer must be used within DrawerProvider");
  return ctx;
}

/** Which film the drawer is showing. Only the drawer itself should need this. */
export function useDrawerTarget(): number | null {
  return useContext(TargetCtx);
}
