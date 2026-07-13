import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthGate } from "@/components/AuthGate";
import { AppShell } from "@/components/shell/AppShell";
import { PrefsProvider } from "@/lib/prefs";
import { ScanProvider } from "@/lib/scan";
import { Activity } from "@/pages/Activity";
import { Dashboard } from "@/pages/Dashboard";
import { DesignSystem } from "@/pages/DesignSystem";
import { Ask } from "@/pages/Ask";
import { Junk } from "@/pages/Junk";
import { Library } from "@/pages/Library";
import { Missing } from "@/pages/Missing";
import { Settings, TasteProfile } from "@/pages/placeholders";

export default function App() {
  return (
    <PrefsProvider>
      <AuthGate>
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
                <Route path="design" element={<DesignSystem />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ScanProvider>
      </AuthGate>
    </PrefsProvider>
  );
}
