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
  IgnoredItem,
  IgnoredListResponse,
  SuggestionListResponse,
  TopupResult,
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
  ResetResponse,
  ReviewRunResponse,
  ScanRun,
  ScanStartResponse,
  ServiceHealth,
  SettingsResponse,
  ShadowDiffResponse,
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
  // The asset token was minted under the old session and dies with it. Changing
  // the password rotates the server's signing secret, so every token issued
  // before it — including this one — stops verifying; the cached copy would go
  // on being sent for the rest of its nominal life, which is up to forty
  // minutes of 401s on every poster and a scan socket that will not open.
  invalidateAssetToken();
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
// How long a page-level read may hang before it becomes a visible error with a
// retry, rather than a spinner that never resolves. Generous on purpose: a
// sleeping free-tier instance takes about thirty seconds to wake, and giving up
// on that would turn a slow first load into a failure. What this catches is the
// case with no end — a database that has stopped answering, a query that never
// returns — which the screen otherwise reports as "still loading", for ever.
export const PAGE_LOAD_TIMEOUT_MS = 45_000;

// Pass timeoutMs for the ones a user sits watching a spinner on, so a hung
// connection surfaces as a retryable error instead of an indefinite "…".
async function request<T>(path: string, init: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  // An explicitly supplied credential wins over the ambient session one: setup
  // carries the deploy token, and on a fresh install a stale session token in
  // storage would otherwise be sent in its place.
  if (token && !headers.has("X-Sift-Token")) headers.set("X-Sift-Token", token);

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
  // `deployToken` is the value of SIFT_SERVER__API_TOKEN. Where a deploy sets
  // one, the server requires it to create the first account — without sending
  // it the wizard simply got a 401 it could not explain.
  authSetup: (username: string, password: string, deployToken?: string) =>
    request<TokenResponse>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ username, password }),
      headers: deployToken ? { "X-Sift-Token": deployToken } : undefined,
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
    // Mint a replacement now rather than leaving the next poster to discover the
    // old one is dead.
    await refreshAssetToken();
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
  junk: (limit = 200) =>
    request<JunkResponse>(`/api/junk?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),
  // The v1-vs-v2 disagreements on the owner's own library. Read-only: v2 computes
  // in shadow and changes nothing, and looking at this is how it earns the right
  // to change something.
  shadowDiff: (limit = 200) =>
    request<ShadowDiffResponse>(
      `/api/junk/shadow-diff?limit=${limit}`,
      {},
      PAGE_LOAD_TIMEOUT_MS,
    ),
  runReview: (limit = 50) =>
    request<ReviewRunResponse>(`/api/review/run?limit=${limit}`, { method: "POST" }),
  upgrades: (limit = 200) => request<UpgradesResponse>(`/api/upgrades?limit=${limit}`),
  missingCollections: () =>
    request<MissingCollectionsResponse>(
      "/api/missing/collections",
      {},
      PAGE_LOAD_TIMEOUT_MS,
    ),
  missingLists: () => request<MissingListsResponse>("/api/missing/lists"),
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
  getProfile: () => request<ProfileResponse>("/api/profile", {}, PAGE_LOAD_TIMEOUT_MS),
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
    request<DuplicatesResponse>(`/api/duplicates?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),

  movieSizes: (limit = 200) =>
    request<MovieSizeResponse>(`/api/storage/movies?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),
  baselines: () =>
    request<BaselinesResponse>("/api/storage/baselines", {}, PAGE_LOAD_TIMEOUT_MS),
  tvStorage: (limit = 200) =>
    request<TvStorageResponse>(`/api/storage/tv?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),
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
  ledger: (limit = 500) =>
    request<LedgerResponse>(`/api/storage/ledger?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),
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
  // The one Missing list: canon minus what you own, minus what you have asked
  // for, minus what you have said no to. Paged rather than capped — the list
  // behind it is tens of thousands deep, so "keep scrolling" is the honest shape.
  suggestions: ({
    tier,
    limit = 60,
    offset = 0,
  }: { tier?: number | null; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (tier) params.set("tier", String(tier));
    return request<SuggestionListResponse>(
      `/api/missing/suggestions?${params.toString()}`,
      {},
      PAGE_LOAD_TIMEOUT_MS,
    );
  },
  // Extend the list past the one that ships with Sift: TMDB discovery, then
  // whichever AI providers are connected. Both write into the same table, so this
  // makes the one list longer rather than opening a second one. Slow by nature —
  // several discovery pages plus a provider round trip — so it gets its own bound.
  topup: () =>
    request<TopupResult>("/api/missing/topup", { method: "POST" }, PAGE_LOAD_TIMEOUT_MS),
  ignoreTitle: (tmdbId: number, title: string, source = "missing") =>
    request<IgnoredItem>("/api/missing/ignore", {
      method: "POST",
      body: JSON.stringify({ tmdb_id: tmdbId, title, source }),
    }),
  ignoredTitles: (limit = 200) =>
    request<IgnoredListResponse>(`/api/missing/ignored?limit=${limit}`, {}, PAGE_LOAD_TIMEOUT_MS),
  unignoreTitle: (tmdbId: number) =>
    request<{ removed: boolean }>(`/api/missing/ignore/${tmdbId}`, { method: "DELETE" }),
};

// A short-lived, read-only credential for the URLs that cannot carry a header —
// <img>, download links, the scan socket. Those URLs end up in proxy logs and
// browser history, so what travels in them expires in minutes and opens nothing
// but the asset. Held in memory only: writing it to storage would give it the
// persistence the whole arrangement exists to avoid.
let assetToken: string | null = null;
let assetTokenAt = 0;
let assetRefresh: Promise<void> | null = null;

/** Forget the minted asset token. Called whenever the session it belongs to changes. */
export function invalidateAssetToken(): void {
  assetToken = null;
  assetTokenAt = 0;
}

export async function refreshAssetToken(): Promise<void> {
  if (assetRefresh) return assetRefresh;
  // Timed out deliberately: the auth gate waits for this before it renders, so a
  // request that hangs must fail rather than hold the whole app behind it.
  assetRefresh = request<{ token: string; expires_in: number }>(
    "/api/auth/asset-token",
    {},
    4000,
  )
    .then((r) => {
      assetToken = r.token;
      // Renew at two thirds of its life, so an image request never races the expiry.
      assetTokenAt = Date.now() + r.expires_in * 1000 * 0.66;
    })
    .catch(() => {
      // Leave the session token in place as the fallback. A failure here must
      // never mean a page of broken thumbnails.
      assetToken = null;
    })
    .finally(() => {
      assetRefresh = null;
    });
  return assetRefresh;
}

export function urlToken(): string | null {
  if (assetToken && Date.now() < assetTokenAt) return assetToken;
  // Missing or stale: kick off a renewal and fall back to the session token for
  // this one request, which is exactly what happened before asset tokens existed.
  //
  // This is a genuine last resort, not the ordinary path. It used to be the
  // ordinary path: the auth gate kicked the refresh off without waiting and
  // rendered immediately, so the first screenful of posters — sixty of them on
  // the library page — carried the thirty-day session token in a query string on
  // every single load. That is the exact leak asset tokens exist to prevent.
  // The gate now waits, so reaching here means the mint actually failed and the
  // choice is between a stale credential in a URL and a page of broken
  // thumbnails.
  void refreshAssetToken();
  return assetToken ?? getToken();
}

// Server-resolved, cached poster for any title (works for Plex-only movies with no
// Radarr artwork). Carries a token as a query param since <img> can't set headers.
export function posterUrl(tmdbId: number): string {
  const token = urlToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/poster/${tmdbId}${q}`;
}

// Build the WebSocket URL for live scan progress, carrying the asset token.
export function scanSocketUrl(scanId: number): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = urlToken();
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${location.host}/ws/scan/${scanId}${q}`;
}
