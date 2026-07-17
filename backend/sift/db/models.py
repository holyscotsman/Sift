"""SQLAlchemy 2.x models for the Sift SQLite snapshot.

Schema mirrors the game plan §6. Identity is keyed on ``tmdb_id`` (the one id that
crosses every source); ``radarr_id`` and ``plex_rating_key`` are the per-source
handles. See ``ingest/normalize.py`` for how the three are reconciled.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (naive ``datetime.utcnow`` is deprecated)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- enums


class RatingSource(enum.StrEnum):
    TMDB = "tmdb"
    IMDB = "imdb"
    USER = "user"


class ActionType(enum.StrEnum):
    ADD = "add"
    MONITOR = "monitor"
    UNMONITOR = "unmonitor"
    DELETE = "delete"


class ActionStatus(enum.StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class ActionActor(enum.StrEnum):
    AUTO = "auto"
    USER = "user"


class ScanStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


# -------------------------------------------------------------------------- tables


class Movie(Base):
    __tablename__ = "movies"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    radarr_id: Mapped[int | None] = mapped_column(Integer, index=True)
    plex_rating_key: Mapped[str | None] = mapped_column(String(64), index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), index=True)

    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    runtime: Mapped[int | None] = mapped_column(Integer)  # minutes
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(String(1024))

    library_section: Mapped[str | None] = mapped_column(String(255), index=True)
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    # `in_plex` is the source of truth for library membership (present & playable in
    # a Plex movie section). `has_file` is Radarr's separate view (file downloaded),
    # kept for duplicate/upgrade analysis but NOT the definition of "in my library".
    in_plex: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    has_file: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    # Radarr's own verdict: the current file's quality is below the profile cutoff,
    # i.e. an upgrade is wanted. Sourced from the movie payload (no extra request);
    # meaningful only when has_file. Drives the deterministic upgrade detector.
    cutoff_unmet: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Owner's standing verdict: never flag this title as junk again. Set from the
    # Junk screen's Keep; survives rescans (a session-only "kept" would resurface
    # the same titles forever).
    keep_override: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Facts for the smarter-junk classifier (populated by TMDB enrichment). Absent →
    # the classifier stays neutral and the numeric score decides.
    original_language: Mapped[str | None] = mapped_column(String(8))
    budget: Mapped[int | None] = mapped_column(BigInteger)
    is_adult: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    us_theatrical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_independent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    ratings: Mapped[list[Rating]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )
    watch_history: Mapped[list[WatchHistory]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )
    score: Mapped[Score | None] = relationship(
        back_populates="movie", cascade="all, delete-orphan", uselist=False
    )
    people: Mapped[list[MoviePerson]] = relationship(
        back_populates="movie", cascade="all, delete-orphan"
    )


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("movie_id", "source", name="uq_rating_movie_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id", ondelete="CASCADE"))
    source: Mapped[RatingSource] = mapped_column(Enum(RatingSource, native_enum=False, length=8))
    value: Mapped[float] = mapped_column(Float)
    votes: Mapped[int | None] = mapped_column(Integer)

    movie: Mapped[Movie] = relationship(back_populates="ratings")


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (
        UniqueConstraint("movie_id", "plex_user", name="uq_watch_movie_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id", ondelete="CASCADE"))
    plex_user: Mapped[str] = mapped_column(String(255))
    plays: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_pct: Mapped[float | None] = mapped_column(Float)
    is_kids_account: Mapped[bool] = mapped_column(Boolean, default=False)

    movie: Mapped[Movie] = relationship(back_populates="watch_history")


class Collection(Base):
    __tablename__ = "collections"

    tmdb_collection_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    name: Mapped[str] = mapped_column(String(512))
    owned_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)

    members: Mapped[list[CollectionMember]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )


class CollectionMember(Base):
    __tablename__ = "collection_members"
    __table_args__ = (
        UniqueConstraint("collection_id", "tmdb_id", name="uq_member_collection_movie"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.tmdb_collection_id", ondelete="CASCADE")
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    owned: Mapped[bool] = mapped_column(Boolean, default=False)

    collection: Mapped[Collection] = relationship(back_populates="members")


class Person(Base):
    __tablename__ = "people"

    # id is the TMDB person id (natural key).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))

    credits: Mapped[list[MoviePerson]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class MoviePerson(Base):
    __tablename__ = "movie_people"
    __table_args__ = (
        UniqueConstraint("movie_id", "person_id", "job", name="uq_movie_person_job"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.tmdb_id", ondelete="CASCADE"))
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    job: Mapped[str] = mapped_column(String(64))  # director / actor / writer / ...

    movie: Mapped[Movie] = relationship(back_populates="people")
    person: Mapped[Person] = relationship(back_populates="credits")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), unique=True
    )
    junk_score: Mapped[float] = mapped_column(Float, default=0.0)
    fit_score: Mapped[float | None] = mapped_column(Float)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_used: Mapped[str | None] = mapped_column(String(128))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    movie: Mapped[Movie] = relationship(back_populates="score")


class Profile(Base):
    """Singleton taste profile (id is pinned to 1)."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    vector: Mapped[bytes | None] = mapped_column()  # embedding blob (LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[ActionType] = mapped_column(Enum(ActionType, native_enum=False, length=16))
    # Not an FK: an `add` targets a movie Sift does not yet own.
    movie_tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, native_enum=False, length=16),
        default=ActionStatus.PROPOSED,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[ActionActor] = mapped_column(
        Enum(ActionActor, native_enum=False, length=8), default=ActionActor.AUTO
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, native_enum=False, length=16), default=ScanStatus.RUNNING
    )
    checkpoints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CuratedListEntry(Base):
    """A title on a curated list (e.g. cult classics, IMDb top). Content is
    human-reviewable: ``review_status`` gates whether it drives keep/remove decisions.
    ``tmdb_id`` is resolved from ``title``/``year`` via TMDB search during a scan."""

    __tablename__ = "curated_list_entries"
    __table_args__ = (UniqueConstraint("list_name", "title", "year", name="uq_curated_entry"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_name: Mapped[str] = mapped_column(String(32), index=True)  # "cult" | "imdb_top"
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")


class MustHaveSuggestion(Base):
    """A must-have title the library is missing. AI (or the curated fallback) may
    *propose* a title, but it is only stored after passing the deterministic
    anti-nonsense gates against TMDB — so a suggestion can never be a hallucinated
    or fringe film. ``status`` tracks the owner's decision; ``dismissed`` titles are
    never re-suggested."""

    __tablename__ = "musthave_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(32), default="curated")  # provider used
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="suggested", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
