import { lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthGate } from "@/components/AuthGate";
import { ToastProvider } from "@/components/Toast";
import { AppShell } from "@/components/shell/AppShell";
import { DrawerProvider } from "@/lib/drawer";
import { PrefsProvider } from "@/lib/prefs";
import { ScanProvider } from "@/lib/scan";

// Route-level code splitting: the login screen and shell load fast; each page's
// chunk arrives on first visit. Pages are named exports, hence the .then() maps.
const Dashboard = lazy(() => import("@/pages/Dashboard").then((m) => ({ default: m.Dashboard })));
const Library = lazy(() => import("@/pages/Library").then((m) => ({ default: m.Library })));
const Missing = lazy(() => import("@/pages/Missing").then((m) => ({ default: m.Missing })));
const Junk = lazy(() => import("@/pages/Junk").then((m) => ({ default: m.Junk })));
const Ask = lazy(() => import("@/pages/Ask").then((m) => ({ default: m.Ask })));
const TasteProfile = lazy(() =>
  import("@/pages/TasteProfile").then((m) => ({ default: m.TasteProfile })),
);
const Activity = lazy(() => import("@/pages/Activity").then((m) => ({ default: m.Activity })));
const Settings = lazy(() => import("@/pages/Settings").then((m) => ({ default: m.Settings })));

export default function App() {
  return (
    <PrefsProvider>
      <ToastProvider>
        <AuthGate>
          <DrawerProvider>
            <ScanProvider>
              <BrowserRouter>
                <Routes>
                  <Route element={<AppShell />}>
                    <Route index element={<Dashboard />} />
                    <Route path="library" element={<Library />} />
                    <Route path="missing" element={<Missing />} />
                    <Route path="junk" element={<Junk />} />
                    <Route path="ask" element={<Ask />} />
                    <Route path="profile" element={<TasteProfile />} />
                    <Route path="activity" element={<Activity />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Routes>
              </BrowserRouter>
            </ScanProvider>
          </DrawerProvider>
        </AuthGate>
      </ToastProvider>
    </PrefsProvider>
  );
}
