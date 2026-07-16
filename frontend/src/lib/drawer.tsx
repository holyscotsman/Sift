// Global movie-drawer state: any surface can open the detail drawer for a tmdb id.

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface DrawerCtx {
  movieId: number | null;
  open: (tmdbId: number) => void;
  close: () => void;
}

const Ctx = createContext<DrawerCtx | null>(null);

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

  const value = useMemo<DrawerCtx>(
    () => ({ movieId, open: setMovieId, close: () => setMovieId(null) }),
    [movieId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDrawer(): DrawerCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDrawer must be used within DrawerProvider");
  return ctx;
}
