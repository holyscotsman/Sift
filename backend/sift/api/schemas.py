"""Pydantic response/request models for the API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..db.models import ActionActor, ActionType


class ServiceHealth(BaseModel):
    service: str
    ok: bool
    detail: str = ""
    latency_ms: float | None = None
    # Anthropic test only: model ids the key can use, so the UI can offer a picker.
    models: list[str] | None = None


class HealthResponse(BaseModel):
    services: list[ServiceHealth]


class Counts(BaseModel):
    movies: int
    owned: int
    monitored: int
    collections: int
    watch_records: int
    # Distinct titles with any watch history (vs. watch_records = raw play rows).
    watched_titles: int = 0
    actions_pending: int
    upgrades: int
    # The two actionable queues: matches the Junk page (keep-overrides respected)
    # and the Missing page's suggested (not dismissed, not now-owned) picks.
    junk_flagged: int = 0
    musthave_pending: int = 0


class StatusResponse(BaseModel):
    scanning: bool
    last_scan_id: int | None
    last_scan_status: str | None
    last_scan_finished_at: datetime | None
    counts: Counts


class MovieOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tmdb_id: int
    radarr_id: int | None
    plex_rating_key: str | None
    imdb_id: str | None
    title: str
    year: int | None
    runtime: int | None
    genres: list[str]
    library_section: str | None
    is_kids: bool
    monitored: bool
    in_plex: bool
    has_file: bool
    quality: str | None
    file_size: int | None
    cutoff_unmet: bool
    poster_url: str | None
    added_at: datetime | None


class MovieListResponse(BaseModel):
    items: list[MovieOut]
    total: int
    page: int
    page_size: int
    # Sum of file_size over the whole filtered set (not just this page), in bytes.
    total_size: int = 0


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    value: float
    votes: int | None


class WatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plex_user: str
    plays: int
    last_played_at: datetime | None
    completion_pct: float | None
    is_kids_account: bool


class SiftScoreOut(BaseModel):
    junk_score: float
    band: str
    rationale: str


class MovieDetail(MovieOut):
    overview: str | None = None
    keywords: list[str] = []
    keep_override: bool = False
    ratings: list[RatingOut] = []
    watch_history: list[WatchOut] = []
    sift_score: SiftScoreOut | None = None


class KeepOverrideIn(BaseModel):
    keep: bool


class KeepOverrideOut(BaseModel):
    tmdb_id: int
    keep_override: bool


class ScanRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    checkpoints: dict[str, Any]
    stats: dict[str, Any]
    error: str | None


class ScanStartResponse(BaseModel):
    scan_run_id: int
    resume: bool


class AuthStatus(BaseModel):
    setup_complete: bool
    username: str | None = None


class ConnectionsIn(BaseModel):
    # {service: {field: value}} — only known fields per service are stored.
    connections: dict[str, dict[str, Any]]


class ConnectionsOut(BaseModel):
    # Secrets are returned as `<field>_set` booleans, never the values.
    connections: dict[str, dict[str, Any]]


class ConnectionTestIn(BaseModel):
    values: dict[str, Any] = {}


class ActionsConfigIn(BaseModel):
    dry_run: bool


class ActionsConfigOut(BaseModel):
    dry_run: bool


class ResetRequest(BaseModel):
    keep_thumbnails: bool = False


class ResetResponse(BaseModel):
    ok: bool
    cleared_posters: int


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class OkResponse(BaseModel):
    ok: bool


class ProposeActionIn(BaseModel):
    type: ActionType
    movie_tmdb_id: int | None = None
    payload: dict[str, Any] = {}
    actor: ActionActor = ActionActor.AUTO
    dry_run: bool = True


class AddMovieIn(BaseModel):
    tmdb_id: int
    title: str


class SignalOut(BaseModel):
    key: str
    label: str
    weight: float
    contribution: float
    available: bool
    detail: str


class JunkCandidate(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    # For the one-click "check it on IMDb" link; None when the id was never resolved.
    imdb_id: str | None = None
    poster_url: str | None
    library_section: str | None
    quality: str | None
    file_size: int | None
    junk_score: float
    band: str
    kids_guard: bool
    rationale: str
    signals: list[SignalOut]
    ai_note: str | None = None


class ReviewRunResponse(BaseModel):
    reviewed: int
    provider: str


class JunkResponse(BaseModel):
    items: list[JunkCandidate]
    total: int


class UpgradeCandidateOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    poster_url: str | None
    library_section: str | None
    quality: str | None
    file_size: int | None
    is_kids: bool


class UpgradesResponse(BaseModel):
    items: list[UpgradeCandidateOut]
    total: int


class CollectionMemberOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    owned: bool


class CollectionGap(BaseModel):
    collection_id: int
    name: str
    owned_count: int
    total_count: int
    members: list[CollectionMemberOut]


class MissingCollectionsResponse(BaseModel):
    collections: list[CollectionGap]


class ListMovie(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    review_status: str


class MissingList(BaseModel):
    name: str
    label: str
    items: list[ListMovie]


class MissingListsResponse(BaseModel):
    lists: list[MissingList]


class MustHaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    title: str
    year: int | None
    reason: str
    source: str
    vote_average: float | None
    vote_count: int | None


class MustHaveListResponse(BaseModel):
    items: list[MustHaveOut]


class MustHaveRunResponse(BaseModel):
    added: int
    considered: int
    provider: str


class CanonMovieOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    vote_average: float | None
    vote_count: int | None
    # Why it's canon: e.g. ["top rated", "blockbuster", "cult classic"].
    sources: list[str] = []


class CanonMissingResponse(BaseModel):
    items: list[CanonMovieOut]
    total: int
    # Canon titles hidden from the list because they've already been requested and
    # are on their way. Surfaced so they're accounted for rather than just gone.
    requested_total: int = 0


class CanonRefreshResponse(BaseModel):
    canon_written: int
    curator_added: int
    missing_total: int


class RecommendedMovie(BaseModel):
    tmdb_id: int
    title: str
    year: int | None
    vote_average: float
    reason: str


class RecommendationsResponse(BaseModel):
    items: list[RecommendedMovie]
    note: str | None = None


class ThresholdsModel(BaseModel):
    min_votes: int
    rating_floor: float
    unwatched_years: int
    junk_cutoff: float
    borderline_cutoff: float


class SettingsResponse(BaseModel):
    connections: list[ServiceHealth]
    thresholds: ThresholdsModel
    ai_configured: bool
    # Both providers usable under tandem — Ask can offer side-by-side compare.
    ai_compare_available: bool = False
    # True when writes are staged only (nothing reaches Radarr). The hosted default.
    actions_dry_run: bool
    # "sqlite" | "postgres" — and whether that means login/config die on redeploy
    # (SQLite on a host with an ephemeral disk, detected via the RENDER env var).
    database_kind: str = "sqlite"
    ephemeral_risk: bool = False
    # True when stored service credentials are encrypted at rest (key material is
    # present in the environment). This is what makes a persistent hosted DB safe.
    secrets_encrypted: bool = False
    # Automatic rescan interval in hours; 0 = off.
    scan_interval_hours: int = 0


class ThresholdPreview(BaseModel):
    junk: int
    borderline: int
    keep: int
    total: int


class DecisionsImportIn(BaseModel):
    # Preview is the default: the real apply requires the explicit flag from the
    # confirm step — an accidental POST can never mutate state.
    dry_run: bool = True
    keep_overrides: list[dict[str, Any]] = []
    dismissed_musthaves: list[dict[str, Any]] = []
    thresholds: dict[str, Any] | None = None


class DecisionsImportOut(BaseModel):
    dry_run: bool
    keeps_applied: int
    keeps_unknown: int
    dismissals_applied: int
    thresholds_restored: bool


class QualityProfileOut(BaseModel):
    id: int
    name: str


class RadarrOptions(BaseModel):
    root_folders: list[str] = []
    quality_profiles: list[QualityProfileOut] = []
    default_root_folder: str | None = None
    default_quality_profile_id: int | None = None


class ScanScheduleIn(BaseModel):
    interval_hours: int


class ScanScheduleOut(BaseModel):
    interval_hours: int


class PosterCacheStats(BaseModel):
    count: int
    bytes: int


class ProfileBucket(BaseModel):
    name: str
    count: int


class ProfileWeights(BaseModel):
    genre: float
    director: float
    cast: float
    keywords: float
    era: float


class ProfileResponse(BaseModel):
    genres: list[ProfileBucket]
    keywords: list[ProfileBucket]
    directors: list[ProfileBucket]
    actors: list[ProfileBucket]
    eras: list[ProfileBucket]
    library_size: int
    weights: ProfileWeights


class AskRequest(BaseModel):
    query: str
    mode: str = "single"  # single | compare (compare needs a 2nd provider)


class AskSource(BaseModel):
    tmdb_id: int
    title: str
    year: int | None


class AskAlternate(BaseModel):
    answer: str
    provider: str
    model: str
    latency_ms: float


class AskResponse(BaseModel):
    answer: str
    provider: str
    model: str
    latency_ms: float
    ai_configured: bool
    sources: list[AskSource]
    # Compare mode: the second provider's phrasing of the SAME retrieval.
    # None in single mode or when the second provider didn't answer.
    alternate: AskAlternate | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    movie_tmdb_id: int | None
    status: str
    payload: dict[str, Any]
    dry_run: bool
    actor: str
    created_at: datetime
    approved_at: datetime | None
    executed_at: datetime | None
    error: str | None


class DuplicateCopyOut(BaseModel):
    rating_key: str
    library_section: str | None = None


class DuplicateGroupOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    copies: list[DuplicateCopyOut]
    # How many copies could go while still keeping the film — always one fewer
    # than the number held.
    surplus: int


class DuplicatesResponse(BaseModel):
    items: list[DuplicateGroupOut]
    # Total removable copies across the whole library, not just this page.
    total_surplus: int


class RestartResponse(BaseModel):
    ok: bool
    # False when nothing will bring the process back (a bare local run), so the
    # UI can warn instead of implying a restart that will not happen.
    supervised: bool
    detail: str


class UpdateResponse(BaseModel):
    ok: bool
    detail: str


class VersionStatus(BaseModel):
    running: str
    # None when the check could not be made (offline, rate limited, private fork).
    # The UI says "couldn't check" rather than claiming you are up to date.
    latest: str | None = None
    update_available: bool = False
    # True when an in-app Update can actually do something about it.
    can_update: bool = False


# ------------------------------------------------------------------------ storage


class SizeFindingOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    # oversized | truncated | bad_rip
    kind: str
    path: str | None = None
    size: int
    duration_ms: int | None = None
    runtime_minutes: int | None = None
    resolution: str | None = None
    video_codec: str | None = None
    # Disk this finding would return. Zero for a bad rip: the file is the whole
    # film and stays on disk until a better copy replaces it.
    bytes_reclaimable: int
    # 0 = nothing of value is lost, 1 = reversible, 2 = a judgement call.
    risk_tier: int
    reasons: list[str] = []


class MovieSizeResponse(BaseModel):
    items: list[SizeFindingOut]
    # Totals span the whole library, not just this page.
    total_reclaimable: int
    oversized_count: int
    truncated_count: int
    bad_rip_count: int
    # Small files inspected and cleared — almost all genuine short films. Reported
    # so the number reads as considered rather than silently dropped.
    short_films_cleared: int


class BucketOut(BaseModel):
    resolution: str
    codec: str
    samples: int
    median_rate: float
    # False when this is a seeded default because the library holds too few files
    # of this kind to establish a norm of its own.
    observed: bool


class BaselinesResponse(BaseModel):
    buckets: list[BucketOut]


class LedgerFindingOut(BaseModel):
    kind: str
    target_kind: str
    target_id: str
    title: str
    detail: str
    bytes_reclaimable: int
    # 0 = nothing of value is lost, 1 = reversible, 2 = a judgement call.
    risk_tier: int
    reversible: bool
    reasons: list[str] = []


class TierSummary(BaseModel):
    tier: int
    label: str
    bytes_reclaimable: int
    count: int


class LedgerResponse(BaseModel):
    items: list[LedgerFindingOut]
    total_reclaimable: int
    tiers: list[TierSummary]


class PlanRequest(BaseModel):
    # How much disk you need back, in bytes.
    target_bytes: int


class PlanStepOut(BaseModel):
    finding: LedgerFindingOut
    running_total: int


class PlanResponse(BaseModel):
    target_bytes: int
    steps: list[PlanStepOut]
    # False when the whole library cannot reach the target — said plainly rather
    # than implied, since a plan that quietly falls short sends you deleting for
    # nothing.
    reached: bool
    total: int
    highest_tier: int


# ---------------------------------------------------------------------- transcode


class FileJobOut(BaseModel):
    id: int
    # delete | transcode
    kind: str = "transcode"
    # What this job is for, in the owner's words.
    label: str | None = None
    action_id: int
    # queued | claimed | done | failed
    status: str
    source_path: str
    source_size: int | None = None
    source_duration_ms: int | None = None
    target_resolution: str | None = None
    target_codec: str | None = None
    # An encode larger than this is a mistake, not a result.
    expected_max_bytes: int | None = None
    error: str | None = None


class FileJobClaimOut(BaseModel):
    # None when there is nothing approved and waiting.
    job: FileJobOut | None = None


class FileJobResultIn(BaseModel):
    ok: bool
    output_path: str | None = None
    # Required for a successful transcode — a success with no numbers behind it
    # cannot be verified, and an unverifiable success is how a failed encode gets
    # swapped in. A delete has nothing to measure, so it is exempt.
    output_size: int | None = None
    output_duration_ms: int | None = None
    error: str | None = None


class AgentCapability(BaseModel):
    # Whether an agent could authenticate at all.
    agent_configured: bool
    # Without Sonarr a downgrade cannot be written back, so Sonarr would simply
    # re-upgrade the season on its next search.
    sonarr_connected: bool


class DuplicateEpisodeOut(BaseModel):
    season_number: int
    episode_number: int
    title: str | None = None
    copies: int
    surplus: int
    bytes_reclaimable: int


class ShowDuplicatesOut(BaseModel):
    tvdb_id: int
    title: str
    library_section: str | None = None
    episodes: list[DuplicateEpisodeOut]
    surplus: int
    bytes_reclaimable: int
    # The files that would go — the best copy of each episode is not among them.
    # Sent so that what you approve is exactly what you were shown, rather than
    # something recomputed after the fact.
    surplus_paths: list[str] = []


class SeasonSizeOut(BaseModel):
    tvdb_id: int
    title: str
    season_number: int
    air_year: int | None = None
    episode_count: int
    total_bytes: int
    bytes_per_hour: float
    per_episode: int
    resolution: str | None = None
    video_codec: str | None = None
    excess: int
    bloated: bool


class InconsistencyOut(BaseModel):
    tvdb_id: int
    title: str
    season_number: int
    # What most of the season is in — the thing the odd episodes differ from.
    common_resolution: str | None = None
    odd_resolutions: dict[str, int] = {}
    rate_outliers: int
    episodes_affected: int
    reasons: list[str] = []


class TvStorageResponse(BaseModel):
    duplicates: list[ShowDuplicatesOut]
    duplicate_bytes: int
    seasons: list[SeasonSizeOut]
    season_excess_bytes: int
    # Seasons that disagree with themselves. Not a reclaim figure — fixing one
    # usually costs space rather than saving it, which is why it is reported
    # separately from the ledger instead of inside it.
    inconsistencies: list[InconsistencyOut]


class ReclaimActIn(BaseModel):
    # show | movie
    target_kind: str
    target_id: str
    # Paths of the surplus copies to remove. Sent by the client from a finding
    # rather than recomputed here, so what you approve is exactly what you saw.
    paths: list[str]
    label: str | None = None


class ReclaimActOut(BaseModel):
    action_id: int
    job_ids: list[int]
    # False when the server is staging rather than issuing — the same floor that
    # governs film deletes.
    dry_run: bool
    detail: str


class SectionPlanOut(BaseModel):
    key: str
    title: str
    # What Plex calls it.
    plex_type: str
    agent: str | None = None
    # What Sift will do with it: movie | show | ignore.
    kind: str
    reason: str
    overridden: bool


class SectionsResponse(BaseModel):
    sections: list[SectionPlanOut]
    detail: str = ""


class SectionKindsIn(BaseModel):
    # {"Cartoons": "show", "Home Videos": "ignore"}
    section_kinds: dict[str, str]


class ShowOut(BaseModel):
    tvdb_id: int
    tmdb_id: int | None = None
    title: str
    year: int | None = None
    status: str | None = None
    network: str | None = None
    genres: list[str] = []
    library_section: str | None = None
    is_kids: bool = False
    monitored: bool = False
    in_plex: bool = False
    # Typical episode length in minutes.
    runtime: int | None = None
    season_count: int = 0
    episode_count: int = 0
    # Summed from the episode files, so this is disk actually in use rather than
    # what Sonarr believes it imported.
    total_size: int = 0
    # The resolution most of the show is in.
    resolution: str | None = None
    plays: int = 0
    last_played_at: datetime | None = None
    mean_completion: float | None = None


class ShowListResponse(BaseModel):
    items: list[ShowOut]
    total: int
    page: int
    page_size: int
    total_size: int


class ShowSuggestionOut(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    overview: str = ""
    poster_path: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    # Which of your shows led here, so a suggestion can be argued with.
    because_of: list[str] = []


class ShowSuggestionsResponse(BaseModel):
    items: list[ShowSuggestionOut]
    # Said plainly when the list is short or empty, rather than leaving a blank
    # panel to be read as a failure.
    detail: str = ""
