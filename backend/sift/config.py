"""Layered configuration for Sift.

Precedence (highest wins): process env (``SIFT_*``) > ``.env`` > ``sift.toml`` >
model defaults. Non-secret config lives in ``sift.toml``; secrets (tokens, keys)
belong in ``.env`` and are held as :class:`~pydantic.SecretStr` so they never leak
into logs or ``repr`` output.

Nested settings use a double-underscore delimiter, e.g. ``SIFT_PLEX__TOKEN``.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# The active TOML path is injected by ``load_settings`` before instantiation so a
# custom source can read it. Module-level rather than a field because pydantic's
# ``settings_customise_sources`` classmethod cannot take extra arguments.
_ACTIVE_TOML_PATH: Path | None = None


class _TomlSource(PydanticBaseSettingsSource):
    """A settings source that reads a TOML file into a nested dict."""

    def __init__(self, settings_cls: type[BaseSettings], path: Path | None) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        if path is not None and path.is_file():
            self._data = tomllib.loads(path.read_text("utf-8"))

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Required abstract method; the real work happens in ``__call__``.
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8756
    # When set, every /api/* request must present this token (Bearer or X-Sift-Token).
    api_token: SecretStr | None = None


class DatabaseConfig(BaseModel):
    # SQLite file path (default). For a persistent hosted deploy, set ``url`` (or the
    # bare ``DATABASE_URL`` env var) to a Postgres URL — e.g. a free Neon database —
    # so login + config survive redeploys on an ephemeral host.
    path: Path = Path("sift.db")
    url: str | None = None

    def target(self) -> str:
        """The connection target: an explicit URL (``SIFT_DATABASE__URL`` or the bare
        ``DATABASE_URL`` env var) wins; otherwise the SQLite path."""
        raw = self.url or os.environ.get("DATABASE_URL")
        return raw.strip() if raw and raw.strip() else str(self.path)


class PlexConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    token: SecretStr | None = None
    # Library section titles that belong to children (kids-guardrail). Items in
    # these sections are marked ``is_kids`` and never auto-flagged for removal.
    kids_sections: list[str] = Field(default_factory=list)


class RadarrConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    api_key: SecretStr | None = None
    # Where add-to-Radarr puts titles. None = first root folder / first quality
    # profile Radarr reports (the historical default); set from Settings.
    default_root_folder: str | None = None
    default_quality_profile_id: int | None = None


class TautulliConfig(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    api_key: SecretStr | None = None
    # Plex usernames belonging to children; their history is tagged distinctly so
    # kids engagement never counts toward adult-library junk scoring.
    kids_accounts: list[str] = Field(default_factory=list)


class TmdbConfig(BaseModel):
    enabled: bool = True
    api_key: SecretStr | None = None
    language: str = "en-US"
    # How many in-Plex titles to enrich per scan (keywords, people, and the facts the
    # smarter-junk classifier needs). Rate-limited; a few thousand covers most
    # libraries. 0 disables enrichment.
    enrich_limit: int = 3000


class JunkThresholds(BaseModel):
    """Deterministic junk-scoring knobs (Phase 1). Data decides; the LLM explains."""

    min_votes: int = 50
    rating_floor: float = 5.0  # on a 0–10 scale
    rating_prior: float = 6.0  # Bayesian prior mean pulled toward on low vote counts
    unwatched_years: int = 3
    low_completion_pct: float = 0.25
    exclude_kids_sections: bool = True
    # Composite junk score (0–100) band cutoffs.
    junk_cutoff: float = 60.0
    borderline_cutoff: float = 40.0


class ActionsConfig(BaseModel):
    """Radarr write behaviour. dry_run stages actions (logged/audited, nothing sent)
    until you explicitly turn it off — the safe default for a hosted instance."""

    dry_run: bool = True


class PostersConfig(BaseModel):
    """On-disk thumbnail cache. Defaults to a ``cache/`` dir beside the database, so
    a Render persistent disk covers both. This is the cache 'reset (keep thumbnails)'
    preserves."""

    cache_dir: Path | None = None


class AIConfig(BaseModel):
    """Provider layer. Never used to decide correctness — AI advises, data decides.

    ``mode`` picks the engine: ``tandem`` uses both providers when configured (the
    local model drafts, Anthropic refines); ``anthropic`` / ``ollama`` pin to one.
    """

    mode: str = "tandem"  # tandem | anthropic | ollama
    local_enabled: bool = False  # is a local Ollama endpoint configured to use?
    local_base_url: str = "http://127.0.0.1:11434"
    local_model: str = "llama3.1"
    anthropic_model: str = "claude-sonnet-5"
    # Entered in the wizard/Settings; falls back to the ANTHROPIC_API_KEY env var.
    anthropic_api_key: SecretStr | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIFT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    plex: PlexConfig = Field(default_factory=PlexConfig)
    radarr: RadarrConfig = Field(default_factory=RadarrConfig)
    tautulli: TautulliConfig = Field(default_factory=TautulliConfig)
    tmdb: TmdbConfig = Field(default_factory=TmdbConfig)
    junk: JunkThresholds = Field(default_factory=JunkThresholds)
    actions: ActionsConfig = Field(default_factory=ActionsConfig)
    posters: PostersConfig = Field(default_factory=PostersConfig)
    ai: AIConfig = Field(default_factory=AIConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Order = priority, highest first. TOML sits below env/.env so secrets in
        # .env always win over anything in sift.toml.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _TomlSource(settings_cls, _ACTIVE_TOML_PATH),
            file_secret_settings,
        )


def load_settings(config_path: str | Path | None = "sift.toml") -> Settings:
    """Load settings, layering ``sift.toml`` under the environment.

    Passing ``config_path=None`` skips the TOML file entirely (useful in tests).
    """
    global _ACTIVE_TOML_PATH
    _ACTIVE_TOML_PATH = Path(config_path) if config_path is not None else None
    return Settings()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings for the running app."""
    return load_settings()
