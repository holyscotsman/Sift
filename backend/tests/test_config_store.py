"""UI-entered connection config: overlay logic + the gated config endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.main import create_app
from sift.services import config_store


def test_overlay_applies_and_masks(settings, factory):
    with factory() as session:
        config_store.set_config(
            session,
            {
                "radarr": {"base_url": "http://radarr.test", "api_key": "rk"},
                "tmdb": {"api_key": "tk", "language": "fr-FR"},
                "anthropic": {"api_key": "sk-x"},
                "ollama": {"base_url": "http://ollama.test", "model": "llama3.1"},
                "bogus": {"x": 1},  # unknown service ignored
            },
        )
        cfg = config_store.get_config(session)

    eff = config_store.apply_to_settings(settings, cfg)
    assert eff.radarr.base_url == "http://radarr.test"
    assert eff.radarr.api_key.get_secret_value() == "rk" and eff.radarr.enabled
    assert eff.tmdb.language == "fr-FR" and eff.tmdb.api_key.get_secret_value() == "tk"
    assert eff.ai.anthropic_api_key.get_secret_value() == "sk-x"
    assert eff.ai.local_enabled and eff.ai.local_base_url == "http://ollama.test"
    assert "bogus" not in cfg

    # Masked view never leaks secrets.
    masked = config_store.masked(cfg)
    assert masked["radarr"] == {"base_url": "http://radarr.test", "api_key_set": True}
    assert masked["anthropic"] == {"api_key_set": True}


def test_none_values_leave_fields_unchanged(settings, factory):
    with factory() as session:
        config_store.set_config(session, {"radarr": {"base_url": "http://a", "api_key": "k1"}})
        # A later patch with api_key=None must not wipe the stored key.
        config_store.set_config(session, {"radarr": {"base_url": "http://b", "api_key": None}})
        cfg = config_store.get_config(session)
    assert cfg["radarr"] == {"base_url": "http://b", "api_key": "k1"}


@pytest.fixture
def client(settings, factory):
    settings.server.api_token = None
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        # Create an account and authenticate (config routes are gated).
        token = c.post(
            "/api/auth/setup", json={"username": "alice", "password": "hunter2hunter2"}
        ).json()["token"]
        c.headers.update({"X-Sift-Token": token})
        yield c


def test_config_endpoints_save_and_reflect(client):
    # Saving connections persists (masked) and takes effect in the live settings.
    put = client.put(
        "/api/config",
        json={"connections": {"radarr": {"base_url": "http://radarr.test", "api_key": "rk"}}},
    )
    assert put.status_code == 200
    assert put.json()["connections"]["radarr"] == {
        "base_url": "http://radarr.test",
        "api_key_set": True,
    }

    got = client.get("/api/config").json()["connections"]
    assert got["radarr"]["base_url"] == "http://radarr.test"
    # The rebuild made Radarr live (enabled) — it now shows up as a real connection.
    conns = {c["service"]: c for c in client.get("/api/settings").json()["connections"]}
    assert conns["radarr"]["service"] == "radarr"


def test_config_test_endpoint_ollama_unreachable(client):
    # Testing an unsaved Ollama URL that isn't up returns ok=False (not a 500).
    r = client.post(
        "/api/config/test/ollama", json={"values": {"base_url": "http://127.0.0.1:1"}}
    )
    assert r.status_code == 200 and r.json()["ok"] is False


def test_config_test_anthropic_verifies_key_and_lists_models(client, monkeypatch):
    # A present key is verified against /v1/models and the ids come back for the
    # UI's model picker; a missing key short-circuits to ok=False.
    from sift.api import routes_config

    async def fake_models(key, **_kw):
        assert key == "sk-x"
        return ["claude-sonnet-5", "claude-haiku-4-5"]

    monkeypatch.setattr(routes_config.anthropic_ai, "list_models", fake_models)
    with_key = client.post("/api/config/test/anthropic", json={"values": {"api_key": "sk-x"}})
    body = with_key.json()
    assert body["ok"] is True and body["models"] == ["claude-sonnet-5", "claude-haiku-4-5"]
    without = client.post("/api/config/test/anthropic", json={"values": {}})
    assert without.json()["ok"] is False


def test_config_test_anthropic_rejected_key_is_reported(client, monkeypatch):
    import httpx

    from sift.api import routes_config

    async def rejected(key, **_kw):
        request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        raise httpx.HTTPStatusError(
            "401", request=request, response=httpx.Response(401, request=request)
        )

    monkeypatch.setattr(routes_config.anthropic_ai, "list_models", rejected)
    r = client.post("/api/config/test/anthropic", json={"values": {"api_key": "sk-bad"}})
    body = r.json()
    assert body["ok"] is False and "rejected" in body["detail"]


def test_ai_engine_mode_saves_and_overlays(client):
    # The AI engine mode round-trips through /api/config and lands in settings.
    put = client.put("/api/config", json={"connections": {"ai": {"mode": "ollama"}}})
    assert put.status_code == 200
    assert put.json()["connections"]["ai"] == {"mode": "ollama"}
    assert client.get("/api/config").json()["connections"]["ai"]["mode"] == "ollama"


def test_ai_engine_mode_invalid_value_is_ignored():
    from sift.config import load_settings
    from sift.services.config_store import apply_to_settings

    base = load_settings(config_path=None)
    eff = apply_to_settings(base, {"ai": {"mode": "chaos"}})
    assert eff.ai.mode == "tandem"  # default survives nonsense
    eff = apply_to_settings(base, {"ai": {"mode": "Anthropic"}})
    assert eff.ai.mode == "anthropic"  # case-insensitive


def test_actions_dry_run_toggle(client):
    # Default is dry-run (staged). The Autonomy toggle flips it live and it sticks.
    assert client.get("/api/config/actions").json()["dry_run"] is True
    put = client.put("/api/config/actions", json={"dry_run": False})
    assert put.status_code == 200 and put.json()["dry_run"] is False
    # Reflected in the effective settings surfaced to the UI.
    assert client.get("/api/settings").json()["actions_dry_run"] is False
    # And back on.
    assert client.put("/api/config/actions", json={"dry_run": True}).json()["dry_run"] is True


def test_reset_wipes_data_and_reopens_wizard(client, factory):
    from sift.db.models import Movie

    client.put(
        "/api/config",
        json={"connections": {"radarr": {"base_url": "http://r", "api_key": "k"}}},
    )
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", in_plex=True))
        session.commit()

    r = client.post("/api/config/reset", json={"keep_thumbnails": True})
    assert r.status_code == 200 and r.json()["ok"] is True

    # Snapshot + config + account are gone: library empty and the wizard is reachable.
    with factory() as session:
        assert session.get(Movie, 603) is None
    # The account was cleared, so setup-status flips back and the gate reopens.
    assert client.get("/api/auth/status").json()["setup_complete"] is False
    assert client.get("/api/config").json()["connections"] == {}


def test_clearing_a_connection_with_empty_strings(client):
    # Save an Ollama URL, then clear it with "" — the overlay must fully disable it.
    from sift.config import load_settings
    from sift.services.config_store import apply_to_settings

    client.put("/api/config", json={"connections": {"ollama": {"base_url": "http://o:11434"}}})
    cleared = client.put(
        "/api/config", json={"connections": {"ollama": {"base_url": "", "model": ""}}}
    )
    assert cleared.status_code == 200

    got = client.get("/api/config").json()["connections"]["ollama"]
    assert got["base_url"] == ""

    base = load_settings(config_path=None)
    eff = apply_to_settings(base, {"ollama": {"base_url": "", "model": ""}})
    assert eff.ai.local_enabled is False
