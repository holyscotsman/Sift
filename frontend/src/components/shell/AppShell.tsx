// The persistent shell around every route: aurora backdrop, floating header +
// top-nav, the scan panel, and the routed page content.

import { Outlet } from "react-router-dom";

import { Aurora } from "@/components/Aurora";

import { Header } from "./Header";
import { ScanPanel } from "./ScanPanel";
import { TopNav } from "./TopNav";

export function AppShell() {
  return (
    <div className="relative min-h-full">
      <Aurora />
      <div className="relative z-10 mx-auto flex min-h-full max-w-page flex-col gap-3 px-3.5 pb-4 pt-3.5 md:px-6">
        <Header />
        <TopNav />
        <main className="pt-3">
          <Outlet />
        </main>
      </div>
      <ScanPanel />
    </div>
  );
}
