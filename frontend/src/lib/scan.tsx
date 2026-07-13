// Scan controller: starts a scan, streams /ws/scan/{id} progress, and shares the
// live state between the header status pill and the floating scan panel.

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, scanSocketUrl } from "./api";
import type { ScanEvent } from "./types";

// Backend pipeline phases (order matters) mapped to friendly labels. Taste-profile
// and scoring phases arrive with Phase 1–2 of the backend.
export const SCAN_PHASES: { key: string; label: string }[] = [
  { key: "radarr", label: "Fetching Radarr catalog" },
  { key: "plex", label: "Reading Plex library" },
  { key: "tautulli", label: "Pulling Tautulli history" },
  { key: "tmdb", label: "Enriching TMDB metadata" },
  { key: "finalize", label: "Finalizing snapshot" },
  { key: "score", label: "Scoring library" },
];

export type PhaseState = "idle" | "active" | "done";

interface ScanCtx {
  scanning: boolean;
  pct: number;
  phaseStates: Record<string, PhaseState>;
  panelOpen: boolean;
  error: string | null;
  start: () => Promise<void>;
  setPanelOpen: (open: boolean) => void;
}

const ScanContext = createContext<ScanCtx | null>(null);

function initialPhases(): Record<string, PhaseState> {
  return Object.fromEntries(SCAN_PHASES.map((p) => [p.key, "idle"]));
}

export function ScanProvider({ children, onComplete }: { children: ReactNode; onComplete?: () => void }) {
  const [scanning, setScanning] = useState(false);
  const [pct, setPct] = useState(0);
  const [phaseStates, setPhaseStates] = useState<Record<string, PhaseState>>(initialPhases);
  const [panelOpen, setPanelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const start = useCallback(async () => {
    if (scanning) {
      setPanelOpen(true);
      return;
    }
    setError(null);
    setPct(0);
    setPhaseStates(initialPhases());
    setScanning(true);
    setPanelOpen(true);
    try {
      const { scan_run_id } = await api.scanStart();
      const ws = new WebSocket(scanSocketUrl(scan_run_id));
      socketRef.current = ws;
      ws.onmessage = (msg) => {
        const evt = JSON.parse(msg.data) as ScanEvent;
        if (evt.event === "progress") {
          const total = evt.total_phases || SCAN_PHASES.length;
          setPhaseStates((prev) => {
            const next = { ...prev };
            if (evt.status === "running") next[evt.phase] = "active";
            else if (evt.status === "done" || evt.status === "skipped") next[evt.phase] = "done";
            return next;
          });
          const done = evt.status === "done" || evt.status === "skipped";
          setPct(Math.min(100, Math.round(((evt.phase_index + (done ? 1 : 0.4)) / total) * 100)));
        } else if (evt.event === "terminal") {
          setPct(100);
          setScanning(false);
          if (evt.status !== "completed") setError(evt.error ?? evt.status);
          onComplete?.();
          window.setTimeout(() => setPanelOpen(false), 1400);
          ws.close();
        }
      };
      ws.onerror = () => setError("scan socket error");
      ws.onclose = () => {
        socketRef.current = null;
        setScanning(false);
      };
    } catch (e) {
      setScanning(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [scanning, onComplete]);

  const value = useMemo<ScanCtx>(
    () => ({ scanning, pct, phaseStates, panelOpen, error, start, setPanelOpen }),
    [scanning, pct, phaseStates, panelOpen, error, start],
  );

  return <ScanContext.Provider value={value}>{children}</ScanContext.Provider>;
}

export function useScan(): ScanCtx {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScan must be used within ScanProvider");
  return ctx;
}
