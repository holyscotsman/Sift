// The persistent shell around every route: aurora backdrop, floating header +
// top-nav, the scan panel, and the routed page content. Pages are lazy chunks —
// the Suspense boundary sits around the outlet so the shell never flashes away
// while a chunk loads.

import { Suspense, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { api } from "@/lib/api";

import { Aurora } from "@/components/Aurora";
import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { MovieDrawer } from "@/components/MovieDrawer";
import { Skeleton } from "@/components/ui";
import { Shortcuts } from "@/lib/shortcuts";

import { Header } from "./Header";
import { ScanPanel } from "./ScanPanel";
import { TopNav } from "./TopNav";

// A quiet footer so bug reports can say what they're running.
function Footer() {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .version()
      .then((v) => {
        if (!cancelled) setVersion(v.version);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  if (!version) return null;
  return (
    <footer className="mt-6 pb-2 text-center text-[11px] text-fg3/70">
      Sift {version} ·{" "}
      <a
        href="https://github.com/holyscotsman/Sift/blob/main/CHANGELOG.md"
        target="_blank"
        rel="noreferrer"
        className="hover:text-fg2"
      >
        changelog
      </a>
    </footer>
  );
}

function PageFallback() {
  return (
    <div className="page-enter">
      <Skeleton className="mb-4 h-8 w-48" />
      <div className="panel p-6">
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}

export function AppShell() {
  return (
    <div className="relative min-h-full">
      <a
        href="#content"
        className="sr-only-focusable"
      >
        Skip to content
      </a>
      <Aurora />
      <div className="relative z-10 mx-auto flex min-h-full max-w-page flex-col gap-3 px-3.5 pb-4 pt-3.5 md:px-6">
        <Header />
        <TopNav />
        <main id="content" className="pt-3">
          <RouteErrorBoundary>
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          </RouteErrorBoundary>
        </main>
        <Footer />
      </div>
      <ScanPanel />
      <MovieDrawer />
      <Shortcuts />
    </div>
  );
}
