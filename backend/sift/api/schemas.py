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


class HealthResponse(BaseModel):
    services: list[ServiceHealth]


class Counts(BaseModel):
    movies: int
    owned: int
    monitored: int
    collections: int
    watch_records: int
    actions_pending: int
    upgrades: int


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
    ratings: list[RatingOut] = []
    watch_history: list[WatchOut] = []
    sift_score: SiftScoreOut | None = None


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
    # True when writes are staged only (nothing reaches Radarr). The hosted default.
    actions_dry_run: bool


class ThresholdPreview(BaseModel):
    junk: int
    borderline: int
    keep: int
    total: int


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


class AskResponse(BaseModel):
    answer: str
    provider: str
    model: str
    latency_ms: float
    ai_configured: bool
    sources: list[AskSource]


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
