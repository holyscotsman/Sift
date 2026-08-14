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
    # Replaces a file with a smaller one. Destructive, so it is gated exactly as
    # a delete is — and never executed by Sift, which has no access to the files.
    TRANSCODE = "transcode"


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


class CanonMovie(Base):
    """The backend's internal canon of theatrical-scale films worth owning.

    Built deterministically — TMDB's top-rated chart, a revenue-sorted
    blockbuster sweep, the curated lists (cult / IMDb top / criterion), and
    already-gated must-have suggestions. Nothing enters on AI say-so. The list
    itself stays backend-only; the Missing page shows canon minus the PLEX
    library (Radarr is deliberately ignored — wanted-but-absent still counts
    as missing)."""

    __tablename__ = "canon_movies"

    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    poster_path: Mapped[str | None] = mapped_column(String(255))
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int | None] = mapped_column(Integer)
    # Why it's canon: e.g. ["top rated", "blockbuster", "cult classic"].
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CanonEntry(Base):
    """The validated canon — films worth owning, from outside this library.

    A *new table* rather than columns on ``curated_list_entries``, for the
    reason recorded throughout this schema: ``create_all`` adds tables on a live
    database and never adds columns, and the import needs an ``imdb_id`` that
    table does not have.

    It arrives keyed by IMDb id and must be resolved to TMDB ids before it can be
    compared with the library, so ``tmdb_id`` is nullable and filled in over
    several scans within a per-scan budget. ``review_status`` records what
    happened: pending, resolved, or unresolvable after repeated attempts.

    ``file_version`` is the version string of the data file a row came from, so a
    refreshed canon reseeds without duplicating and without wiping resolutions
    already earned.
    """

    __tablename__ = "canon_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imdb_id: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer)
    # 1 is the strongest claim to canon, 4 the weakest. Tiers 1-3 protect an
    # owned title from the junk queue; tier 4 is advisory only.
    tier: Mapped[int] = mapped_column(Integer, index=True, default=4)
    # Which pillars vouch for it: criterion, cult, award, imdb_wr, canon_patch.
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Criterion spine number where the entry carries one.
    spine: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    votes: Mapped[int | None] = mapped_column(Integer)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    resolve_attempts: Mapped[int] = mapped_column(Integer, default=0)
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    file_version: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PlexCopy(Base):
    """One row per *item* in a Plex movie section — not per film.

    ``movies`` is keyed by tmdb_id, so a library holding three rips of the same
    film collapsed into a single row and only the last rating key survived. That
    made duplicates structurally invisible (you cannot report on what you never
    recorded) and quietly cost watch history: plays are matched back by rating
    key, so any recorded against the discarded copies were dropped on the floor.

    A separate table rather than extra columns on ``movies`` is deliberate — the
    schema is created with ``create_all``, which adds new *tables* to an existing
    database but never new *columns*, so this deploys to a live instance with no
    migration step.
    """

    __tablename__ = "plex_copies"

    # Plex's own identifier for the item; the natural key, and what watch history
    # is reported against.
    rating_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    movie_tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("movies.tmdb_id", ondelete="CASCADE"), index=True
    )
    library_section: Mapped[str | None] = mapped_column(String(255))
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str | None] = mapped_column(String(512))
    # Set when a scan no longer sees this item, so a copy you removed stops being
    # reported as a duplicate without needing the row deleted mid-scan.
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Show(Base):
    """A TV series. Keyed on ``tvdb_id`` because that is the id Sonarr and Plex's
    TV agent both speak; ``tmdb_id`` rides along for metadata enrichment.

    Watch aggregates live here rather than in a TV twin of ``watch_history``:
    ``watch_history`` is foreign-keyed to ``movies.tmdb_id`` and cannot hold a TV
    row at all, and the quality heuristic only ever asks show-level questions —
    how completely it is watched, how recently, and at what resolution it is
    actually streamed. Per-episode play rows would be a larger table answering a
    question nobody asks.
    """

    __tablename__ = "shows"

    tvdb_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sonarr_id: Mapped[int | None] = mapped_column(Integer, index=True)
    plex_rating_key: Mapped[str | None] = mapped_column(String(64), index=True)

    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str | None] = mapped_column(String(32))
    network: Mapped[str | None] = mapped_column(String(255))
    genres: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    original_language: Mapped[str | None] = mapped_column(String(8))
    # Typical episode length in minutes; separates a 22-minute sitcom from a
    # 55-minute drama, which is a real signal for how much the picture matters.
    runtime: Mapped[int | None] = mapped_column(Integer)

    library_section: Mapped[str | None] = mapped_column(String(255), index=True)
    is_kids: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    in_plex: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    quality_profile_id: Mapped[int | None] = mapped_column(Integer)

    # Watch aggregates (Tautulli). Absent means "no evidence", never "unwatched".
    plays: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mean_completion: Mapped[float | None] = mapped_column(Float)
    # The height actually delivered to a player, which is what the library is
    # really being asked for — a show only ever streamed at 720p does not need 4K.
    typical_stream_height: Mapped[int | None] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    seasons: Mapped[list[Season]] = relationship(
        back_populates="show", cascade="all, delete-orphan"
    )


class Season(Base):
    """A season, and the grain at which quality is judged.

    Per-show is the wrong grain and it matters: Scrubs season 1 (2001) is
    SD-native while season 9 (2010) is HD-native, and SpongeBob runs from 1999
    into the 2020s. ``air_year`` is what the source-ceiling rule reads.
    """

    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("show_id", "season_number", name="uq_season_show_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(
        ForeignKey("shows.tvdb_id", ondelete="CASCADE"), index=True
    )
    season_number: Mapped[int] = mapped_column(Integer)
    air_year: Mapped[int | None] = mapped_column(Integer)
    episode_count: Mapped[int] = mapped_column(Integer, default=0)
    episode_file_count: Mapped[int] = mapped_column(Integer, default=0)
    # Sonarr reports this per season for free on the series payload, so a rough
    # size is available without walking every episode file.
    size_on_disk: Mapped[int | None] = mapped_column(BigInteger)

    show: Mapped[Show] = relationship(back_populates="seasons")
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="season", cascade="all, delete-orphan"
    )


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("season_id", "episode_number", name="uq_episode_season_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"), index=True
    )
    episode_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(512))
    air_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sonarr_episode_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # The duplicate detector's exactness rests on this. A single "S01E01-E02" file
    # is one file covering two episodes, and Sonarr gives both episodes the same
    # file id — so a shared id is a multi-episode file, not a duplicate, with no
    # heuristic required.
    sonarr_episode_file_id: Mapped[int | None] = mapped_column(Integer, index=True)
    plex_rating_key: Mapped[str | None] = mapped_column(String(64), index=True)
    has_file: Mapped[bool] = mapped_column(Boolean, default=False)

    season: Mapped[Season] = relationship(back_populates="episodes")


class FileJob(Base):
    """Work on a file that only the machine holding it can do.

    Sift runs where the media is not. It cannot delete a surplus episode or
    re-encode a season, and pretending otherwise is how a tool like this loses
    someone's library. So it records an approved intention and waits: an agent on
    the box with the files claims the job, does the work, checks the result, and
    reports back. Same philosophy as the restart and update endpoints — hand
    control to the host rather than pretend to have it.

    The agent polls. A hook would need the media box reachable from wherever Sift
    runs, which behind NAT it is not, and polling opens no inbound port.

    **Why this exists rather than a Sonarr call.** Sonarr can delete an episode
    file it imported. The surplus copies duplicate detection finds are the ones
    Sonarr never imported — manual copies, failed imports, leftovers — so its API
    has no handle on them. The file path is the only thing that does.

    ``source_size`` and ``source_duration_ms`` are recorded at approval time so a
    result can be checked against what was actually there. An encode that comes
    back materially shorter than its source is a failed encode, and swapping it in
    would destroy the episode quietly.

    (Supersedes the ``transcode_jobs`` table from 2607.16.0, which never held a
    row because nothing created one. That table cannot gain a ``kind`` column —
    ``create_all`` adds tables to a live database but never columns — so this is a
    new one. The old table is left in place, empty and unreferenced.)
    """

    __tablename__ = "file_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # delete | transcode
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # Not a hard FK: the action is the authority, and a job whose action has gone
    # must fail closed rather than cascade away unnoticed.
    action_id: Mapped[int] = mapped_column(Integer, index=True)
    # queued | claimed | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)

    source_path: Mapped[str] = mapped_column(String(1024))
    source_size: Mapped[int | None] = mapped_column(BigInteger)
    source_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    # Transcode only.
    target_resolution: Mapped[str | None] = mapped_column(String(16))
    target_codec: Mapped[str | None] = mapped_column(String(32))
    expected_max_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # What this job is for, in the owner's words, so the agent log and the
    # Activity feed both read as something a person decided.
    label: Mapped[str | None] = mapped_column(String(512))

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MediaFile(Base):
    """One row per video file on disk — for a movie or a TV episode alike.

    Size alone cannot tell you whether a file is wasteful. A 30 GB film is
    unremarkable as a three-hour 4K remux and absurd as a ninety-minute 1080p, and
    the only thing that separates them is **bytes per hour at a given resolution
    and codec**. That calculation needs duration, resolution and codec, none of
    which Sift recorded: ``Movie.file_size`` is a bare byte count and
    ``Movie.quality`` is Radarr's free-text profile name.

    The data was already arriving and being discarded. ``normalize_radarr_movie``
    opens ``raw["movieFile"]`` to read the quality name and drops ``mediaInfo``,
    ``path`` and ``size`` from the same dict; Plex's section listing carries a
    ``Media``/``Part`` block and the normalizer keeps seven fields. So this costs
    no extra requests — only the parsing.

    One table for both movies and episodes rather than two is deliberate: every
    bitrate query, outlier rule and test then works on one shape, and the movie
    half of the feature ships before any TV model exists. Exactly one of
    ``movie_tmdb_id`` / ``episode_id`` is set.

    A separate table rather than columns on ``movies`` follows ``PlexCopy`` above —
    ``create_all`` adds new tables to a live database but never new columns.
    """

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Plex's identity for the item this file belongs to. Nullable because Radarr
    # can report a file for a title Plex has not scanned yet.
    rating_key: Mapped[str | None] = mapped_column(String(64), index=True)
    movie_tmdb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    episode_id: Mapped[int | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), index=True
    )

    # The natural key for de-duplication across sources: two sources reporting the
    # same path are describing one file, not two.
    path: Mapped[str | None] = mapped_column(String(1024), index=True)
    container: Mapped[str | None] = mapped_column(String(32))
    size: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    # Normalised rung on the ladder ("480p"/"720p"/"1080p"/"2160p"), derived from
    # height where possible. Stored rather than computed so the outlier queries can
    # group in SQL.
    resolution: Mapped[str | None] = mapped_column(String(16), index=True)
    video_codec: Mapped[str | None] = mapped_column(String(32))
    audio_codec: Mapped[str | None] = mapped_column(String(32))
    # Which presentation this file belongs to. Files sharing a group are one
    # thing split across several files — the two halves of a long episode — and
    # every one of them is needed. Separate groups are separate copies, and those
    # are the ones that can go. Plex models exactly this distinction as Part
    # entries under a Media, so the answer is read rather than guessed.
    part_group: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="plex")
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
