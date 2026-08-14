// Thin typed fetch client for the Sift API. Same-origin in production (FastAPI
// serves the built UI); the Vite dev server proxies /api and /ws to :8756.

import type {
  BaselinesResponse,
  DuplicatesResponse,
  LedgerResponse,
  MovieSizeResponse,
  PlanResponse,
  ReclaimActResult,
  SectionsResponse,
  ShowListResponse,
  ShowSuggestionsResponse,
  TvStorageResponse,
  VersionStatus,
  RestartResponse,
  UpdateResponse,
  ActionRecord,
  ActionType,
  AskResponse,
  AuthStatus,
  CanonMissingResponse,
  ValidatedCanonResponse,
  CanonRefreshResponse,
  ConnectionsResponse,
  DecisionsImportResult,
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

// Most calls have no deadline — an AI answer or a scan can legitimately run long.
// Pass timeoutMs for the ones a user sits watching a spinner on, so a hung
// connection surfaces as a retryable error instead of an indefinite "…".
async function request<T>(path: string, init: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("X-Sift-Token", token);

  let signal = init.signal;
  let timeoutController: AbortController | null = null;
  let timeoutId: number | undefined;
  if (timeoutMs) {
    timeoutController = new AbortController();
    const onCallerAbort = () => timeoutController?.abort();
    if (init.signal) {
      if (init.signal.aborted) timeoutController.abort();
      else init.signal.addEventListener("abort", onCallerAbort);
    }
    timeoutId = window.setTimeout(() => timeoutController?.abort(), timeoutMs);
    signal = timeoutController.signal;
  }

  let res: Response;
  try {
    res = await fetch(path, { ...init, headers, signal });
  } catch (e) {
    // Our own timeout abort looks identical to a caller cancelling — distinguish
    // them, or a dead connection and a deliberate cancel read the same.
    if (timeoutController?.signal.aborted && !init.signal?.aborted) {
      throw new ApiError("Timed out waiting for a response — check the connection.", 0);
    }
    throw e;
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
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
  // Changing the password rotates the server's signing secret, which signs out
  // every other session. The replacement token is stored immediately so this
  // device is not one of them.
  changePassword: async (currentPassword: string, newPassword: string) => {
    const result = await request<TokenResponse>("/api/auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    setToken(result.token);
    return result;
  },
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
  sections: () => request<SectionsResponse>("/api/config/sections"),
  saveSections: (sectionKinds: Record<string, string>) =>
    request<SectionsResponse>("/api/config/sections", {
      method: "PUT",
      body: JSON.stringify({ section_kinds: sectionKinds }),
    }),
  getActionsConfig: () => request<{ dry_run: boolean }>("/api/config/actions"),
  setActionsConfig: (dryRun: boolean) =>
    request<{ dry_run: boolean }>("/api/config/actions", {
      method: "PUT",
      body: JSON.stringify({ dry_run: dryRun }),
    }),
  movies: (query: MovieQuery = {}) =>
    request<MovieListResponse>(`/api/movies${queryString(query as Record<string, unknown>)}`),
  shows: (query: Record<string, unknown> = {}) =>
    request<ShowListResponse>(`/api/shows${queryString(query)}`),
  showSections: () => request<string[]>("/api/shows/sections"),
  showSuggestions: () => request<ShowSuggestionsResponse>("/api/shows/suggestions"),
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
  mustHaveList: (status: "suggested" | "dismissed" = "suggested") =>
    request<MustHaveListResponse>(`/api/musthave?status=${status}`),
  mustHaveRun: (limit = 20) =>
    request<MustHaveRunResponse>(`/api/musthave/run?limit=${limit}`, { method: "POST" }),
  mustHaveDismiss: (id: number) =>
    request<unknown>(`/api/musthave/${id}/dismiss`, { method: "POST" }),
  mustHaveRestore: (id: number) =>
    request<unknown>(`/api/musthave/${id}/restore`, { method: "POST" }),
  movieSections: () => request<string[]>("/api/movies/sections"),
  importDecisions: (backup: Record<string, unknown>, dryRun: boolean) =>
    request<DecisionsImportResult>("/api/import/decisions", {
      method: "POST",
      body: JSON.stringify({ ...backup, dry_run: dryRun }),
    }),
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
    request<ActionRecord>(
      "/api/actions/add",
      { method: "POST", body: JSON.stringify({ tmdb_id: tmdbId, title }) },
      30_000,
    ),
  // Requests route through Overseerr when configured, else fall back to Radarr.
  // Bounded, so a hung connection to either service becomes a retryable error
  // rather than a button stuck on "…" forever.
  requestMovie: (tmdbId: number, title: string) =>
    request<ActionRecord>(
      "/api/actions/request",
      { method: "POST", body: JSON.stringify({ tmdb_id: tmdbId, title }) },
      30_000,
    ),
  duplicates: (limit = 200) =>
    request<DuplicatesResponse>(`/api/duplicates?limit=${limit}`),

  movieSizes: (limit = 200) =>
    request<MovieSizeResponse>(`/api/storage/movies?limit=${limit}`),
  baselines: () => request<BaselinesResponse>("/api/storage/baselines"),
  tvStorage: (limit = 200) => request<TvStorageResponse>(`/api/storage/tv?limit=${limit}`),
  actOnFinding: (body: {
    target_kind: string;
    target_id: string;
    paths: string[];
    label?: string;
  }) =>
    request<ReclaimActResult>("/api/storage/act", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ledger: (limit = 500) => request<LedgerResponse>(`/api/storage/ledger?limit=${limit}`),
  reclaimPlan: (targetBytes: number) =>
    request<PlanResponse>("/api/storage/plan", {
      method: "POST",
      body: JSON.stringify({ target_bytes: targetBytes }),
    }),
  // Restart hands control to the host: it stops the process and the platform
  // brings it back. `supervised: false` means nothing will.
  versionStatus: () => request<VersionStatus>("/api/system/version"),
  restart: () => request<RestartResponse>("/api/system/restart", { method: "POST" }, 20_000),
  update: () => request<UpdateResponse>("/api/system/update", { method: "POST" }, 40_000),
  canonMissing: (limit = 500) =>
    request<CanonMissingResponse>(`/api/missing/canon?limit=${limit}`),
  canonRefresh: () =>
    request<CanonRefreshResponse>("/api/missing/canon/refresh", { method: "POST" }),
  // The validated ten-thousand-title canon, distinct from canonMissing above,
  // which serves the smaller list Sift assembles for itself from TMDB charts.
  validatedCanon: ({ tier, limit }: { tier?: number | null; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (tier) params.set("tier", String(tier));
    if (limit) params.set("limit", String(limit));
    const query = params.toString();
    return request<ValidatedCanonResponse>(`/api/musthave/canon${query ? `?${query}` : ""}`);
  },
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
