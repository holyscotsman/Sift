// The persistent shell around every route: aurora backdrop, floating header +
// top-nav, the scan panel, and the routed page content. Pages are lazy chunks —
// the Suspense boundary sits around the outlet so the shell never flashes away
// while a chunk loads.

import { Suspense } from "react";
import { Outlet } from "react-router-dom";

import { Aurora } from "@/components/Aurora";
import { MovieDrawer } from "@/components/MovieDrawer";
import { Skeleton } from "@/components/ui";

import { Header } from "./Header";
import { ScanPanel } from "./ScanPanel";
import { TopNav } from "./TopNav";

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
      <Aurora />
      <div className="relative z-10 mx-auto flex min-h-full max-w-page flex-col gap-3 px-3.5 pb-4 pt-3.5 md:px-6">
        <Header />
        <TopNav />
        <main className="pt-3">
          <Suspense fallback={<PageFallback />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      <ScanPanel />
      <MovieDrawer />
    </div>
  );
}
