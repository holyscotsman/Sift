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
  MustHaveListResponse,
  MustHaveRunResponse,
  PosterCacheStats,
  ProfileResponse,
  ProfileWeights,
  RadarrOptions,
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
    // A dead session (token invalidated by a secret rotation or DB reset) should
    // drop the app back to the login screen, not leave every page silently broken.
    // Auth endpoints are excluded — a wrong password is not a session death.
    if (res.status === 401 && token && !path.startsWith("/api/auth/")) {
      setToken(null);
      window.dispatchEvent(new Event("sift:unauthorized"));
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
  version: () => request<{ name: string; version: string }>("/api/version"),
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
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
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
  setKeepOverride: (tmdbId: number, keep: boolean) =>
    request<{ tmdb_id: number; keep_override: boolean }>(`/api/movies/${tmdbId}/keep`, {
      method: "POST",
      body: JSON.stringify({ keep }),
    }),
  scanStart: (resumeId?: number) =>
    request<ScanStartResponse>(`/api/scan${resumeId ? `?resume_id=${resumeId}` : ""}`, {
      method: "POST",
    }),
  scanGet: (id: number) => request<ScanRun>(`/api/scan/${id}`),
  scanList: (limit = 5) => request<ScanRun[]>(`/api/scan?limit=${limit}`),
  ask: (query: string, mode = "single", signal?: AbortSignal) =>
    request<AskResponse>("/api/ask", {
      method: "POST",
      body: JSON.stringify({ query, mode }),
      signal,
    }),
  junk: (limit = 200) => request<JunkResponse>(`/api/junk?limit=${limit}`),
  runReview: (limit = 50) =>
    request<ReviewRunResponse>(`/api/review/run?limit=${limit}`, { method: "POST" }),
  upgrades: (limit = 200) => request<UpgradesResponse>(`/api/upgrades?limit=${limit}`),
  missingCollections: () =>
    request<MissingCollectionsResponse>("/api/missing/collections"),
  missingLists: () => request<MissingListsResponse>("/api/missing/lists"),
  missingRecommendations: () =>
    request<RecommendationsResponse>("/api/missing/recommendations"),
  mustHaveList: () => request<MustHaveListResponse>("/api/musthave"),
  mustHaveRun: (limit = 20) =>
    request<MustHaveRunResponse>(`/api/musthave/run?limit=${limit}`, { method: "POST" }),
  mustHaveDismiss: (id: number) =>
    request<unknown>(`/api/musthave/${id}/dismiss`, { method: "POST" }),
  activity: (limit = 50) => request<ActionRecord[]>(`/api/activity?limit=${limit}`),
  getProfile: () => request<ProfileResponse>("/api/profile"),
  saveWeights: (w: ProfileWeights) =>
    request<ProfileResponse>("/api/profile/weights", { method: "PUT", body: JSON.stringify(w) }),
  getSettings: () => request<SettingsResponse>("/api/settings"),
  radarrOptions: () => request<RadarrOptions>("/api/settings/radarr_options"),
  saveScanSchedule: (intervalHours: number) =>
    request<{ interval_hours: number }>("/api/settings/scan_schedule", {
      method: "PUT",
      body: JSON.stringify({ interval_hours: intervalHours }),
    }),
  posterStats: () => request<PosterCacheStats>("/api/posters/stats"),
  clearPosterCache: () =>
    request<PosterCacheStats>("/api/posters/clear", { method: "POST" }),
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
    actor?: "auto" | "user";
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
