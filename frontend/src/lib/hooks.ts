// Small dependency-free data hooks (fetch + polling). Server state that needs
// caching across routes can graduate to TanStack Query later.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { ActionRecord, HealthResponse, StatusResponse } from "./types";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
}

function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[], pollMs?: number): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(() => {
    let cancelled = false;
    fetcherRef
      .current()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setLoading(true);
    const cancel = run();
    let timer: number | undefined;
    // Poll ticks skip while the tab is hidden (no point refreshing a screen
    // nobody sees); coming back refetches immediately so it's never stale.
    const tick = () => {
      if (!document.hidden) run();
    };
    const onVisible = () => {
      if (!document.hidden) run();
    };
    if (pollMs) {
      timer = window.setInterval(tick, pollMs);
      document.addEventListener("visibilitychange", onVisible);
    }
    return () => {
      cancel();
      if (timer) window.clearInterval(timer);
      if (pollMs) document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, pollMs, ...deps]);

  return { data, error, loading, refetch: run };
}


// Two components can want the same polled endpoint at once — TopNav and Dashboard
// both show status, HealthDots and Dashboard both show health. Each `useAsync`
// holds its own state and its own interval, so without sharing the server answers
// the identical question twice every tick, for as long as the tab is open. That is
// a permanent background cost rather than a one-off, and on a metered database it
// is charged for ever.
//
// Deliberately not a cache library: one map of in-flight promises and one of
// recent results, both keyed by endpoint. A caller arriving inside the window
// joins the request already running, or takes the result that just landed.
const inflight = new Map<string, Promise<unknown>>();
const recent = new Map<string, { at: number; value: unknown }>();

function shared<T>(key: string, fetcher: () => Promise<T>, ttlMs: number): Promise<T> {
  const fresh = recent.get(key);
  if (fresh && Date.now() - fresh.at < ttlMs) return Promise.resolve(fresh.value as T);
  const running = inflight.get(key) as Promise<T> | undefined;
  if (running) return running;
  const started = fetcher()
    .then((value) => {
      recent.set(key, { at: Date.now(), value });
      return value;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, started);
  return started;
}

/** Drop everything the shared window is holding.
 *
 * The two maps above are module-level, which is what makes the window work at
 * all — and it means they outlive anything that mounts and unmounts, including a
 * test. Without this, the second test in a file reads the first one's data for
 * the length of the TTL and passes for the wrong reason.
 *
 * Also correct to call whenever the session identity changes: the cache would
 * otherwise hand the next caller a status read taken under the previous token.
 */
export function resetSharedCache(): void {
  inflight.clear();
  recent.clear();
}

// The window is a fraction of the poll interval, so a second consumer joins the
// tick rather than doubling it, and successive ticks still fetch for real.
export function useHealth(pollMs = 20000): AsyncState<HealthResponse> {
  return useAsync(() => shared("health", () => api.health(), pollMs * 0.75), [], pollMs);
}

export function useStatus(pollMs = 8000): AsyncState<StatusResponse> {
  return useAsync(() => shared("status", () => api.status(), pollMs * 0.75), [], pollMs);
}

export function useActivity(limit = 50): AsyncState<ActionRecord[]> {
  return useAsync(() => api.activity(limit), [limit]);
}
