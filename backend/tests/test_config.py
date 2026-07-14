"""Config layering + secret handling."""

from __future__ import annotations

from pydantic import SecretStr

from sift.config import load_settings


def test_defaults_without_toml_or_env(monkeypatch):
    monkeypatch.delenv("SIFT_SERVER__PORT", raising=False)
    s = load_settings(config_path=None)
    assert s.server.host == "127.0.0.1"
    assert s.server.port == 8756
    assert s.plex.token is None


def test_database_target_prefers_url(monkeypatch):
    from sift.config import DatabaseConfig

    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Default: the SQLite path.
    assert DatabaseConfig().target() == "sift.db"
    # Bare DATABASE_URL env is honoured when no explicit url is set.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    assert DatabaseConfig().target() == "postgresql://u:p@host/db"
    # An explicit url wins over the env var.
    assert DatabaseConfig(url="postgres://x/y").target() == "postgres://x/y"


def test_resolve_url_normalizes_postgres():
    from sift.db.session import _resolve_url

    # sqlite path + :memory:
    assert _resolve_url("sift.db") == "sqlite:///sift.db"
    assert _resolve_url(":memory:") == "sqlite://"
    # legacy scheme upgraded + sslmode added
    assert _resolve_url("postgres://u:p@h/db") == "postgresql://u:p@h/db?sslmode=require"
    # existing query string keeps its params, sslmode appended with &
    assert _resolve_url("postgresql://u:p@h/db?a=1") == "postgresql://u:p@h/db?a=1&sslmode=require"
    # explicit sslmode is left alone
    assert _resolve_url("postgresql://u@h/db?sslmode=disable") == "postgresql://u@h/db?sslmode=disable"


def test_toml_is_read(tmp_path):
    toml = tmp_path / "sift.toml"
    toml.write_text(
        "[server]\nport = 9001\n[plex]\nbase_url = 'http://plex:32400'\n"
    )
    s = load_settings(config_path=toml)
    assert s.server.port == 9001
    assert s.plex.base_url == "http://plex:32400"


def test_env_overrides_toml(tmp_path, monkeypatch):
    toml = tmp_path / "sift.toml"
    toml.write_text("[server]\nport = 9001\n")
    monkeypatch.setenv("SIFT_SERVER__PORT", "7777")
    s = load_settings(config_path=toml)
    # env must win over the TOML value (secret-override precedence).
    assert s.server.port == 7777


def test_secrets_are_secretstr_and_redacted(monkeypatch):
    monkeypatch.setenv("SIFT_RADARR__API_KEY", "supersecret")
    s = load_settings(config_path=None)
    assert isinstance(s.radarr.api_key, SecretStr)
    assert s.radarr.api_key.get_secret_value() == "supersecret"
    # The secret must not leak through repr/str.
    assert "supersecret" not in repr(s.radarr)
    assert "supersecret" not in str(s.radarr.api_key)
