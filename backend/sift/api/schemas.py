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
    poster_url: str | None
    added_at: datetime | None


class MovieListResponse(BaseModel):
    items: list[MovieOut]
    total: int
    page: int
    page_size: int


class RatingOut(BaseModel):
    source: str
    value: float
    votes: int | None


class WatchOut(BaseModel):
    plex_user: str
    plays: int
    last_played_at: datetime | None
    completion_pct: float | None
    is_kids_account: bool


class MovieDetail(MovieOut):
    overview: str | None = None
    keywords: list[str] = []
    ratings: list[RatingOut] = []
    watch_history: list[WatchOut] = []


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


class ProposeActionIn(BaseModel):
    type: ActionType
    movie_tmdb_id: int | None = None
    payload: dict[str, Any] = {}
    actor: ActionActor = ActionActor.AUTO
    dry_run: bool = True


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


class JunkResponse(BaseModel):
    items: list[JunkCandidate]
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


class RecommendationsResponse(BaseModel):
    items: list[dict[str, Any]]
    note: str | None = None


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
