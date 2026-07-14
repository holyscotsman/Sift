// Mirrors backend/sift/api/schemas.py. Keep in sync with the API surface.

export type ServiceName = "plex" | "radarr" | "tautulli" | "tmdb";

export interface AuthStatus {
  setup_complete: boolean;
  username: string | null;
}

export interface TokenResponse {
  token: string;
  username: string;
}

// {service: {field: value | `${field}_set`: boolean}} — secrets come back as *_set.
export type Connections = Record<string, Record<string, unknown>>;

export interface ConnectionsResponse {
  connections: Connections;
}

export interface ResetResponse {
  ok: boolean;
  cleared_posters: number;
}

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
  upgrades: number;
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
  cutoff_unmet: boolean;
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

export interface Signal {
  key: string;
  label: string;
  weight: number;
  contribution: number;
  available: boolean;
  detail: string;
}

export interface JunkCandidate {
  tmdb_id: number;
  title: string;
  year: number | null;
  poster_url: string | null;
  library_section: string | null;
  quality: string | null;
  file_size: number | null;
  junk_score: number;
  band: "keep" | "borderline" | "junk";
  kids_guard: boolean;
  rationale: string;
  signals: Signal[];
  ai_note: string | null;
}

export interface ReviewRunResponse {
  reviewed: number;
  provider: string;
}

export interface JunkResponse {
  items: JunkCandidate[];
  total: number;
}

export interface CollectionMember {
  tmdb_id: number;
  title: string;
  year: number | null;
  owned: boolean;
}

export interface CollectionGap {
  collection_id: number;
  name: string;
  owned_count: number;
  total_count: number;
  members: CollectionMember[];
}

export interface MissingCollectionsResponse {
  collections: CollectionGap[];
}

export interface ListMovie {
  tmdb_id: number;
  title: string;
  year: number | null;
  review_status: string;
}

export interface MissingList {
  name: string;
  label: string;
  items: ListMovie[];
}

export interface MissingListsResponse {
  lists: MissingList[];
}

export interface UpgradeCandidate {
  tmdb_id: number;
  title: string;
  year: number | null;
  poster_url: string | null;
  library_section: string | null;
  quality: string | null;
  file_size: number | null;
  is_kids: boolean;
}

export interface UpgradesResponse {
  items: UpgradeCandidate[];
  total: number;
}

export interface ProfileBucket {
  name: string;
  count: number;
}

export interface ProfileWeights {
  genre: number;
  director: number;
  cast: number;
  keywords: number;
  era: number;
}

export interface ProfileResponse {
  genres: ProfileBucket[];
  keywords: ProfileBucket[];
  directors: ProfileBucket[];
  actors: ProfileBucket[];
  eras: ProfileBucket[];
  library_size: number;
  weights: ProfileWeights;
}

export interface RatingOut {
  source: string;
  value: number;
  votes: number | null;
}

export interface WatchOut {
  plex_user: string;
  plays: number;
  last_played_at: string | null;
  completion_pct: number | null;
  is_kids_account: boolean;
}

export interface SiftScore {
  junk_score: number;
  band: string;
  rationale: string;
}

export interface MovieDetail extends Movie {
  overview: string | null;
  keywords: string[];
  ratings: RatingOut[];
  watch_history: WatchOut[];
  sift_score: SiftScore | null;
}

export interface Thresholds {
  min_votes: number;
  rating_floor: number;
  unwatched_years: number;
  junk_cutoff: number;
  borderline_cutoff: number;
}

export interface SettingsResponse {
  connections: ServiceHealth[];
  thresholds: Thresholds;
  ai_configured: boolean;
  actions_dry_run: boolean;
}

export interface ThresholdPreview {
  junk: number;
  borderline: number;
  keep: number;
  total: number;
}

export interface AskSource {
  tmdb_id: number;
  title: string;
  year: number | null;
}

export interface AskResponse {
  answer: string;
  provider: string;
  model: string;
  latency_ms: number;
  ai_configured: boolean;
  sources: AskSource[];
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
