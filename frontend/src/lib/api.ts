// Thin typed fetch client for the Sift API. Same-origin in production (FastAPI
// serves the built UI); the Vite dev server proxies /api and /ws to :8756.

import type {
  ActionRecord,
  ActionType,
  AskResponse,
  HealthResponse,
  JunkResponse,
  MissingCollectionsResponse,
  MovieListResponse,
  ScanRun,
  ScanStartResponse,
  StatusResponse,
} from "./types";

const TOKEN_KEY = "sift_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("X-Sift-Token", token);

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface MovieQuery {
  q?: string;
  section?: string;
  is_kids?: boolean;
  monitored?: boolean;
  in_plex?: boolean;
  has_file?: boolean;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

function queryString(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  status: () => request<StatusResponse>("/api/status"),
  movies: (query: MovieQuery = {}) =>
    request<MovieListResponse>(`/api/movies${queryString(query as Record<string, unknown>)}`),
  scanStart: (resumeId?: number) =>
    request<ScanStartResponse>(`/api/scan${resumeId ? `?resume_id=${resumeId}` : ""}`, {
      method: "POST",
    }),
  scanGet: (id: number) => request<ScanRun>(`/api/scan/${id}`),
  ask: (query: string, mode = "single") =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ query, mode }) }),
  junk: (limit = 200) => request<JunkResponse>(`/api/junk?limit=${limit}`),
  missingCollections: () =>
    request<MissingCollectionsResponse>("/api/missing/collections"),
  activity: (limit = 50) => request<ActionRecord[]>(`/api/activity?limit=${limit}`),
  proposeAction: (body: {
    type: ActionType;
    movie_tmdb_id?: number | null;
    payload?: Record<string, unknown>;
  }) => request<ActionRecord>("/api/actions", { method: "POST", body: JSON.stringify(body) }),
  approveAction: (id: number) =>
    request<ActionRecord>(`/api/actions/${id}/approve`, { method: "POST" }),
  rejectAction: (id: number) =>
    request<ActionRecord>(`/api/actions/${id}/reject`, { method: "POST" }),
};

// Build the WebSocket URL for live scan progress, carrying the API token.
export function scanSocketUrl(scanId: number): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${location.host}/ws/scan/${scanId}${q}`;
}
