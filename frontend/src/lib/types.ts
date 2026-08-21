// Mirrors backend/sift/api/schemas.py. Keep in sync with the API surface.

export type ServiceName = "plex" | "radarr" | "tautulli" | "tmdb";

export interface AuthStatus {
  setup_complete: boolean;
  username: string | null;
  /** First-run account creation needs the deploy's access token. */
  setup_requires_token?: boolean;
}

export interface TokenResponse {
  token: string;
  username: string;
}

// {service: {field: value | `${field}_set`: boolean}} — secrets come back as *_set.
export type Connections = Record<string, Record<string, unknown>>;

export interface ConnectionsResponse {
  connections: Connections;
  /** {service: [field]} for secrets stored under a key that has since changed. */
  unreadable?: Record<string, string[]>;
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
  // Anthropic test only: model ids the verified key can use (feeds the picker).
  models?: string[] | null;
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
  // Distinct titles with any watch history (watch_records counts raw play rows).
  watched_titles: number;
  actions_pending: number;
  upgrades: number;
  // The two actionable queues: Junk page candidates and pending Must-Have picks.
  junk_flagged: number;
  musthave_pending: number;
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
  // Sum of file_size across the whole filtered set, in bytes.
  total_size: number;
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
  // For the one-click IMDb link; null when the id was never resolved.
  imdb_id: string | null;
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

export interface MustHaveItem {
  id: number;
  tmdb_id: number;
  title: string;
  year: number | null;
  reason: string;
  source: string;
  vote_average: number | null;
  vote_count: number | null;
}

export interface MustHaveListResponse {
  items: MustHaveItem[];
}

export interface MustHaveRunResponse {
  added: number;
  considered: number;
  provider: string;
}

export interface CanonMovieItem {
  tmdb_id: number;
  title: string;
  year: number | null;
  vote_average: number | null;
  vote_count: number | null;
  // Why it's canon: e.g. ["top rated", "blockbuster", "cult classic"].
  sources: string[];
}

export interface CanonMissingResponse {
  items: CanonMovieItem[];
  total: number;
  // Hidden from the list because they've already been requested and are on the way.
  requested_total: number;
}

// One film on the unified Missing list.
//
// `reasons` is now sentences rather than tags — "You own 3 films by Akira
// Kurosawa", "Thriller is 22% of your library" — because they are counted from
// the library rather than read off a source list. It still deliberately never
// says which list the film came from: the built-in list is meant to be invisible.
export interface SuggestionItem {
  tmdb_id: number;
  title: string;
  year: number | null;
  tier: number;
  reasons: string[];
  rating: number | null;
  votes: number | null;
  // All three may be absent — IMDb records no genres for a few hundred entries,
  // and a card must render perfectly well without them.
  genres: string[];
  runtime: number | null;
  directors: string[];
}

export interface SuggestionListResponse {
  items: SuggestionItem[];
  // `null` means *not measured on this request*, which is not the same as zero.
  // These only change when you act, so the server computes them for the first
  // page of a list and skips them for the pages that continue it. Keep whatever
  // you already had when they come back null.
  total: number | null;
  // Subtracted from the list rather than absent from it.
  requested_total: number | null;
  ignored_total: number | null;
}

export interface TopupResult {
  added: number;
  remaining: number;
  // False when nothing was attempted — no TMDB, or the list is still deep enough
  // that spending API budget would buy nothing. `note` says which.
  ran: boolean;
  considered: number;
  note: string | null;
}

export interface IgnoredItem {
  tmdb_id: number;
  title: string;
  source: string;
}

export interface IgnoredListResponse {
  items: IgnoredItem[];
  total: number;
}

export interface CanonRefreshResponse {
  canon_written: number;
  curator_added: number;
  missing_total: number;
}

export interface RecommendedMovie {
  tmdb_id: number;
  title: string;
  year: number | null;
  vote_average: number;
  reason: string;
}

export interface RecommendationsResponse {
  items: RecommendedMovie[];
  note: string | null;
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
  keep_override: boolean;
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
  // Both providers usable under tandem — Ask can offer side-by-side compare.
  ai_compare_available: boolean;
  actions_dry_run: boolean;
  database_kind: string;
  ephemeral_risk: boolean;
  // Are stored service keys encrypted at rest? Turns itself on when the instance
  // has key material (SIFT_SECRET_KEY, else the access token).
  secrets_encrypted: boolean;
  scan_interval_hours: number;
}

export interface PosterCacheStats {
  count: number;
  bytes: number;
}

export interface DecisionsImportResult {
  dry_run: boolean;
  keeps_applied: number;
  keeps_unknown: number;
  dismissals_applied: number;
  thresholds_restored: boolean;
}

export interface QualityProfile {
  id: number;
  name: string;
}

export interface RadarrOptions {
  root_folders: string[];
  quality_profiles: QualityProfile[];
  default_root_folder: string | null;
  default_quality_profile_id: number | null;
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

export interface AskAlternate {
  answer: string;
  provider: string;
  model: string;
  latency_ms: number;
}

export interface AskResponse {
  answer: string;
  provider: string;
  model: string;
  latency_ms: number;
  ai_configured: boolean;
  sources: AskSource[];
  // Compare mode: the second provider's phrasing of the same retrieval.
  alternate: AskAlternate | null;
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

export interface DuplicateCopy {
  rating_key: string;
  library_section: string | null;
}

export interface DuplicateGroup {
  tmdb_id: number;
  title: string;
  year: number | null;
  copies: DuplicateCopy[];
  // How many copies could go while still keeping the film.
  surplus: number;
}

export interface DuplicatesResponse {
  items: DuplicateGroup[];
  total_surplus: number;
}

export interface RestartResponse {
  ok: boolean;
  // False when nothing will bring the process back (a bare local run).
  supervised: boolean;
  detail: string;
}

export interface UpdateResponse {
  ok: boolean;
  detail: string;
}

export interface VersionStatus {
  running: string;
  // null when the check couldn't be made — shown as "couldn't check", never as
  // "up to date", since claiming currency you can't verify is the misleading case.
  latest: string | null;
  update_available: boolean;
  // Whether an in-app Update can actually act (a deploy hook is configured).
  can_update: boolean;
}

// ------------------------------------------------------------------- storage

export interface SizeFinding {
  tmdb_id: number;
  title: string;
  year: number | null;
  // oversized | truncated | bad_rip
  kind: string;
  path: string | null;
  size: number;
  duration_ms: number | null;
  runtime_minutes: number | null;
  resolution: string | null;
  video_codec: string | null;
  // Zero for a bad rip: the file is the whole film and stays on disk until a
  // better copy replaces it.
  bytes_reclaimable: number;
  // 0 = nothing of value is lost, 1 = reversible, 2 = a judgement call.
  risk_tier: number;
  reasons: string[];
}

export interface MovieSizeResponse {
  items: SizeFinding[];
  total_reclaimable: number;
  oversized_count: number;
  truncated_count: number;
  bad_rip_count: number;
  short_films_cleared: number;
}

export interface Bucket {
  resolution: string;
  codec: string;
  samples: number;
  median_rate: number;
  // False when this is a seeded default rather than measured from your library.
  observed: boolean;
}

export interface BaselinesResponse {
  buckets: Bucket[];
}

export interface LedgerFinding {
  kind: string;
  target_kind: string;
  target_id: string;
  title: string;
  detail: string;
  bytes_reclaimable: number;
  // 0 = nothing of value is lost, 1 = reversible, 2 = a judgement call.
  risk_tier: number;
  reversible: boolean;
  reasons: string[];
}

export interface TierSummary {
  tier: number;
  label: string;
  bytes_reclaimable: number;
  count: number;
}

export interface LedgerResponse {
  items: LedgerFinding[];
  total_reclaimable: number;
  tiers: TierSummary[];
}

export interface PlanStep {
  finding: LedgerFinding;
  running_total: number;
}

export interface PlanResponse {
  target_bytes: number;
  steps: PlanStep[];
  // False when the whole library cannot reach the target.
  reached: boolean;
  total: number;
  highest_tier: number;
}

export interface DuplicateEpisode {
  season_number: number;
  episode_number: number;
  title: string | null;
  copies: number;
  surplus: number;
  bytes_reclaimable: number;
}

export interface ShowDuplicates {
  tvdb_id: number;
  title: string;
  library_section: string | null;
  episodes: DuplicateEpisode[];
  surplus: number;
  bytes_reclaimable: number;
  // The files that would go. The best copy of each episode is not among them.
  surplus_paths: string[];
}

export interface SeasonSize {
  tvdb_id: number;
  title: string;
  season_number: number;
  air_year: number | null;
  episode_count: number;
  total_bytes: number;
  bytes_per_hour: number;
  per_episode: number;
  resolution: string | null;
  video_codec: string | null;
  excess: number;
  bloated: boolean;
}

export interface Inconsistency {
  tvdb_id: number;
  title: string;
  season_number: number;
  common_resolution: string | null;
  odd_resolutions: Record<string, number>;
  rate_outliers: number;
  episodes_affected: number;
  reasons: string[];
}

export interface TvStorageResponse {
  duplicates: ShowDuplicates[];
  duplicate_bytes: number;
  seasons: SeasonSize[];
  season_excess_bytes: number;
  // Not a reclaim figure — fixing one usually costs space.
  inconsistencies: Inconsistency[];
}

export interface ReclaimActResult {
  action_id: number;
  job_ids: number[];
  // False when the server is staging rather than issuing.
  dry_run: boolean;
  detail: string;
}

export interface SectionPlan {
  key: string;
  title: string;
  // What Plex calls it.
  plex_type: string;
  agent: string | null;
  // What Sift will do: movie | show | ignore.
  kind: string;
  reason: string;
  overridden: boolean;
}

export interface SectionsResponse {
  sections: SectionPlan[];
  detail: string;
}

export interface ShowSummary {
  tvdb_id: number;
  tmdb_id: number | null;
  title: string;
  year: number | null;
  status: string | null;
  network: string | null;
  genres: string[];
  library_section: string | null;
  is_kids: boolean;
  monitored: boolean;
  in_plex: boolean;
  runtime: number | null;
  season_count: number;
  episode_count: number;
  // Summed from the episode files — disk actually in use.
  total_size: number;
  resolution: string | null;
  plays: number;
  last_played_at: string | null;
  mean_completion: number | null;
}

export interface ShowListResponse {
  items: ShowSummary[];
  total: number;
  page: number;
  page_size: number;
  total_size: number;
}

export interface ShowSuggestion {
  tmdb_id: number;
  title: string;
  year: number | null;
  overview: string;
  poster_path: string | null;
  vote_average: number | null;
  vote_count: number | null;
  // Which of your shows led here.
  because_of: string[];
}

export interface ShowSuggestionsResponse {
  items: ShowSuggestion[];
  detail: string;
}

// The *validated* canon — the ten-thousand-title list imported from Criterion,
// the cult canon, award records and broad consensus. Distinct from CanonMovie
// above, which is the smaller list Sift builds for itself from TMDB charts.
export interface CanonCoverage {
  total: number;
  owned: number;
  resolved: number;
  unresolved: number;
  unresolvable: number;
}

export interface ValidatedCanonItem {
  tmdb_id: number;
  imdb_id: string | null;
  title: string;
  year: number | null;
  tier: number;
  sources: string[];
  spine: number | null;
  rating: number | null;
  votes: number | null;
}

export interface ValidatedCanonResponse {
  items: ValidatedCanonItem[];
  total: number;
  coverage: CanonCoverage;
}

/** One title where the shadow (v2) score disagrees with the live (v1) one. */
export interface ShadowDiffRow {
  tmdb_id: number;
  title: string;
  year: number | null;
  v1_band: string;
  v1_score: number;
  v2_band: string;
  v2_score: number;
  v2_rule: string | null;
  v2_confidence: number;
}

export interface ShadowDiffResponse {
  items: ShadowDiffRow[];
  compared: number;
  disagreements: number;
  v2_stricter: number;
  v2_gentler: number;
  // v2 declining to answer — not a rung on the keep/borderline/junk ladder.
  v2_abstained: number;
}
