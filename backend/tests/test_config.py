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
