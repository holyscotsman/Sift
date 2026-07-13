// Mirrors backend/sift/api/schemas.py. Keep in sync with the API surface.

export type ServiceName = "plex" | "radarr" | "tautulli" | "tmdb";

export interface ServiceHealth {
  service: string;
  ok: boolean;
  detail: string;
  latency_ms: number | null;
}

export interface HealthResponse {
  services: ServiceHealth[];
}

export interface Counts {
  movies: number;
  owned: number;
  monitored: number;
  collections: number;
  watch_records: number;
  actions_pending: number;
}

export interface StatusResponse {
  scanning: boolean;
  last_scan_id: number | null;
  last_scan_status: string | null;
  last_scan_finished_at: string | null;
  counts: Counts;
}

export interface Movie {
  tmdb_id: number;
  radarr_id: number | null;
  plex_rating_key: string | null;
  imdb_id: string | null;
  title: string;
  year: number | null;
  runtime: number | null;
  genres: string[];
  library_section: string | null;
  is_kids: boolean;
  monitored: boolean;
  in_plex: boolean;
  has_file: boolean;
  quality: string | null;
  file_size: number | null;
  poster_url: string | null;
  added_at: string | null;
}

export interface MovieListResponse {
  items: Movie[];
  total: number;
  page: number;
  page_size: number;
}

export interface ScanRun {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  checkpoints: Record<string, { status: string; counts?: Record<string, number>; at?: string }>;
  stats: Record<string, number>;
  error: string | null;
}

export interface ScanStartResponse {
  scan_run_id: number;
  resume: boolean;
}

export type ActionType = "add" | "monitor" | "unmonitor" | "delete";
export type ActionStatus = "proposed" | "approved" | "rejected" | "executed" | "failed";

export interface ActionRecord {
  id: number;
  type: ActionType;
  movie_tmdb_id: number | null;
  status: ActionStatus;
  payload: Record<string, unknown>;
  dry_run: boolean;
  actor: string;
  created_at: string;
  approved_at: string | null;
  executed_at: string | null;
  error: string | null;
}

// Live scan progress frames pushed over /ws/scan/{id}.
export interface ScanProgressEvent {
  event: "progress";
  scan_run_id: number;
  phase: string;
  phase_index: number;
  total_phases: number;
  status: "running" | "done" | "skipped" | "error";
  message: string;
  counts: Record<string, number>;
}

export interface ScanTerminalEvent {
  event: "terminal";
  status: string;
  stats?: Record<string, number>;
  error?: string;
}

export type ScanEvent = ScanProgressEvent | ScanTerminalEvent;
