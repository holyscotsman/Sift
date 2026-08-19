// Shared scaffolding for component tests.
//
// Pages here sit inside a stack of providers and a router. Rendering one without
// them throws, and a test that works around that by rendering a fragment of the
// component is testing something the app never runs.

import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { ToastProvider } from "@/components/Toast";
import { DrawerProvider } from "@/lib/drawer";
import { PrefsProvider } from "@/lib/prefs";
import { ScanProvider } from "@/lib/scan";

function Providers({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <PrefsProvider>
        <ToastProvider>
          <DrawerProvider>
            <ScanProvider>{children}</ScanProvider>
          </DrawerProvider>
        </ToastProvider>
      </PrefsProvider>
    </MemoryRouter>
  );
}

export function renderPage(ui: ReactElement): RenderResult {
  return render(ui, { wrapper: Providers });
}

/** A junk candidate with only the fields a row actually reads filled in. */
export function candidate(overrides: Record<string, unknown> = {}) {
  return {
    tmdb_id: 603,
    title: "The Matrix",
    year: 1999,
    imdb_id: "tt0133093",
    poster_url: null,
    library_section: "Films",
    quality: "1080p",
    file_size: 8_000_000_000,
    junk_score: 72,
    band: "junk",
    kids_guard: false,
    rationale: "Nobody has heard of it.",
    signals: [],
    ai_note: null,
    ...overrides,
  };
}
