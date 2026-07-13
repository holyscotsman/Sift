// Small dependency-free data hooks (fetch + polling). Server state that needs
// caching across routes can graduate to TanStack Query later.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { MovieQuery } from "./api";
import type {
  ActionRecord,
  HealthResponse,
  MovieListResponse,
  StatusResponse,
} from "./types";

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
    if (pollMs) timer = window.setInterval(run, pollMs);
    return () => {
      cancel();
      if (timer) window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, pollMs, ...deps]);

  return { data, error, loading, refetch: run };
}

export function useHealth(pollMs = 20000): AsyncState<HealthResponse> {
  return useAsync(() => api.health(), [], pollMs);
}

export function useStatus(pollMs = 8000): AsyncState<StatusResponse> {
  return useAsync(() => api.status(), [], pollMs);
}

export function useMovies(query: MovieQuery): AsyncState<MovieListResponse> {
  const key = JSON.stringify(query);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useAsync(() => api.movies(query), [key]);
}

export function useActivity(limit = 50): AsyncState<ActionRecord[]> {
  return useAsync(() => api.activity(limit), [limit]);
}
