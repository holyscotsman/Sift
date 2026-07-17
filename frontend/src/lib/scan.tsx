// Scan controller: starts a scan, streams /ws/scan/{id} progress, and shares the
// live state between the header status pill and the floating scan panel.

import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, scanSocketUrl } from "./api";
import type { ScanEvent } from "./types";

// Backend pipeline phases (order matters — must mirror ingest/pipeline.PHASES).
export const SCAN_PHASES: { key: string; label: string }[] = [
  { key: "plex", label: "Reading Plex catalog" },
  { key: "radarr", label: "Reading Radarr catalog" },
  { key: "tautulli", label: "Pulling Tautulli history" },
  { key: "tmdb", label: "Grabbing TMDB metadata" },
  { key: "finalize", label: "Finalizing snapshot" },
  { key: "score", label: "Scoring library" },
  { key: "ai", label: "AI analysis" },
];

export type PhaseState = "idle" | "active" | "done";

interface ScanCtx {
  scanning: boolean;
  pct: number;
  phaseStates: Record<string, PhaseState>;
  panelOpen: boolean;
  error: string | null;
  start: (opts?: { silent?: boolean }) => Promise<void>;
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
  const pollRef = useRef<number | null>(null);
  const finishedRef = useRef(false);

  const silentRef = useRef(false);

  const finish = useCallback(
    (status: string, err?: string | null) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      socketRef.current?.close();
      socketRef.current = null;
      setPct(100);
      setScanning(false);
      if (status !== "completed" && !silentRef.current) setError(err || status);
      onComplete?.();
      window.setTimeout(() => setPanelOpen(false), 1400);
    },
    [onComplete],
  );

  const start = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = Boolean(opts?.silent);
    if (scanning) {
      if (!silent) setPanelOpen(true);
      return;
    }
    silentRef.current = silent;
    finishedRef.current = false;
    setError(null);
    setPct(0);
    setPhaseStates(initialPhases());
    setScanning(true);
    // Silent mode (wizard auto-scan): work in the background, no panel, no toasts —
    // the header pill still reflects progress for anyone who looks.
    if (!silent) setPanelOpen(true);
    try {
      const { scan_run_id } = await api.scanStart();

      // WebSocket: snappy live progress when it's reachable.
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
          const p = Math.round(((evt.phase_index + (done ? 1 : 0.4)) / total) * 100);
          setPct((prev) => Math.min(100, Math.max(prev, p)));
        } else if (evt.event === "terminal") {
          finish(evt.status, "error" in evt ? evt.error : null);
        }
      };
      // A socket error/close is NOT the end — the poller below is the source of
      // truth, so progress still completes even if the WS is blocked.
      ws.onclose = () => {
        if (socketRef.current === ws) socketRef.current = null;
      };

      // Polling fallback: reconcile from the scan record every 1.5s. Immune to WS
      // auth/proxy issues, so the bar never gets stuck.
      const poll = async () => {
        try {
          const run = await api.scanGet(scan_run_id);
          const cps = run.checkpoints || {};
          let done = 0;
          setPhaseStates((prev) => {
            const next = { ...prev };
            for (const ph of SCAN_PHASES) {
              const st = cps[ph.key]?.status;
              if (st === "done" || st === "skipped") {
                next[ph.key] = "done";
                done++;
              }
            }
            if (run.status === "running") {
              const active = SCAN_PHASES.find((ph) => next[ph.key] !== "done");
              if (active) next[active.key] = "active";
            }
            return next;
          });
          const base = Math.round((done / SCAN_PHASES.length) * 100);
          setPct((prev) => Math.max(prev, run.status === "running" ? Math.min(base, 96) : 100));
          if (run.status !== "running") finish(run.status, run.error);
        } catch {
          /* transient — try again next tick */
        }
      };
      pollRef.current = window.setInterval(poll, 1500);
      void poll();
    } catch (e) {
      finish("failed", e instanceof Error ? e.message : String(e));
    }
  }, [scanning, finish]);

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
