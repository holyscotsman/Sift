// Thin typed fetch client for the Sift API. Same-origin in production (FastAPI
// serves the built UI); the Vite dev server proxies /api and /ws to :8756.

import type {
  ActionRecord,
  ActionType,
  AskResponse,
  AuthStatus,
  ConnectionsResponse,
  HealthResponse,
  JunkResponse,
  MissingCollectionsResponse,
  MissingListsResponse,
  MovieDetail,
  MovieListResponse,
  ProfileResponse,
  ProfileWeights,
  RecommendationsResponse,
  ResetResponse,
  ReviewRunResponse,
  ScanRun,
  ScanStartResponse,
  ServiceHealth,
  SettingsResponse,
  StatusResponse,
  ThresholdPreview,
  Thresholds,
  TokenResponse,
  UpgradesResponse,
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
  cutoff_unmet?: boolean;
  starts_with?: string;
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
  // Auth (open endpoints — the way in).
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  authSetup: (username: string, password: string) =>
    request<TokenResponse>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  authLogin: (username: string, password: string) =>
    request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  // In-app connection config.
  getConfig: () => request<ConnectionsResponse>("/api/config"),
  saveConfig: (connections: Record<string, Record<string, unknown>>) =>
    request<ConnectionsResponse>("/api/config", {
      method: "PUT",
      body: JSON.stringify({ connections }),
    }),
  testConfig: (service: string, values: Record<string, unknown>) =>
    request<ServiceHealth>(`/api/config/test/${service}`, {
      method: "POST",
      body: JSON.stringify({ values }),
    }),
  resetInstance: (keepThumbnails: boolean) =>
    request<ResetResponse>("/api/config/reset", {
      method: "POST",
      body: JSON.stringify({ keep_thumbnails: keepThumbnails }),
    }),
  getActionsConfig: () => request<{ dry_run: boolean }>("/api/config/actions"),
  setActionsConfig: (dryRun: boolean) =>
    request<{ dry_run: boolean }>("/api/config/actions", {
      method: "PUT",
      body: JSON.stringify({ dry_run: dryRun }),
    }),
  movies: (query: MovieQuery = {}) =>
    request<MovieListResponse>(`/api/movies${queryString(query as Record<string, unknown>)}`),
  movie: (tmdbId: number) => request<MovieDetail>(`/api/movies/${tmdbId}`),
  scanStart: (resumeId?: number) =>
    request<ScanStartResponse>(`/api/scan${resumeId ? `?resume_id=${resumeId}` : ""}`, {
      method: "POST",
    }),
  scanGet: (id: number) => request<ScanRun>(`/api/scan/${id}`),
  ask: (query: string, mode = "single") =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ query, mode }) }),
  junk: (limit = 200) => request<JunkResponse>(`/api/junk?limit=${limit}`),
  runReview: (limit = 50) =>
    request<ReviewRunResponse>(`/api/review/run?limit=${limit}`, { method: "POST" }),
  upgrades: (limit = 200) => request<UpgradesResponse>(`/api/upgrades?limit=${limit}`),
  missingCollections: () =>
    request<MissingCollectionsResponse>("/api/missing/collections"),
  missingLists: () => request<MissingListsResponse>("/api/missing/lists"),
  missingRecommendations: () =>
    request<RecommendationsResponse>("/api/missing/recommendations"),
  activity: (limit = 50) => request<ActionRecord[]>(`/api/activity?limit=${limit}`),
  getProfile: () => request<ProfileResponse>("/api/profile"),
  saveWeights: (w: ProfileWeights) =>
    request<ProfileResponse>("/api/profile/weights", { method: "PUT", body: JSON.stringify(w) }),
  getSettings: () => request<SettingsResponse>("/api/settings"),
  previewThresholds: (t: Thresholds) =>
    request<ThresholdPreview>("/api/settings/thresholds/preview", {
      method: "POST",
      body: JSON.stringify(t),
    }),
  saveThresholds: (t: Thresholds) =>
    request<ThresholdPreview>("/api/settings/thresholds", {
      method: "PUT",
      body: JSON.stringify(t),
    }),
  testConnection: (service: string) =>
    request<ServiceHealth>(`/api/settings/test/${service}`, { method: "POST" }),
  proposeAction: (body: {
    type: ActionType;
    movie_tmdb_id?: number | null;
    payload?: Record<string, unknown>;
    dry_run?: boolean;
  }) => request<ActionRecord>("/api/actions", { method: "POST", body: JSON.stringify(body) }),
  approveAction: (id: number) =>
    request<ActionRecord>(`/api/actions/${id}/approve`, { method: "POST" }),
  rejectAction: (id: number) =>
    request<ActionRecord>(`/api/actions/${id}/reject`, { method: "POST" }),
  executeAction: (id: number) =>
    request<ActionRecord>(`/api/actions/${id}/execute`, { method: "POST" }),
  addMovie: (tmdbId: number, title: string) =>
    request<ActionRecord>("/api/actions/add", {
      method: "POST",
      body: JSON.stringify({ tmdb_id: tmdbId, title }),
    }),
};

// Server-resolved, cached poster for any title (works for Plex-only movies with no
// Radarr artwork). Carries the token as a query param since <img> can't set headers.
export function posterUrl(tmdbId: number): string {
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/poster/${tmdbId}${q}`;
}

// Build the WebSocket URL for live scan progress, carrying the API token.
export function scanSocketUrl(scanId: number): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${location.host}/ws/scan/${scanId}${q}`;
}
