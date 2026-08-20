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


def test_base_urls_are_normalized_on_save(factory):
    from sift.services import config_store

    with factory() as session:
        cfg = config_store.set_config(
            session,
            {
                "radarr": {"base_url": " radarr.local:7878/ "},
                "plex": {"base_url": "https://plex.local:32400//"},
            },
        )
    # Missing scheme → http:// added; trailing slashes trimmed; https preserved.
    assert cfg["radarr"]["base_url"] == "http://radarr.local:7878"
    assert cfg["plex"]["base_url"] == "https://plex.local:32400"


def test_stale_stored_urls_normalize_on_overlay(settings):
    from sift.services import config_store

    eff = config_store.apply_to_settings(
        settings, {"tautulli": {"base_url": "tautulli.local:8181/", "api_key": "k"}}
    )
    assert eff.tautulli.base_url == "http://tautulli.local:8181"


def test_mounted_volume_suppresses_the_ephemeral_warning(settings, monkeypatch):
    """A SQLite file on a Render Disk / Fly volume persists, so the 'your data resets
    on redeploy' warning must not fire — it would be telling the owner to fix
    something they already fixed."""
    from pathlib import Path

    # The default relative path on Render: genuinely ephemeral.
    settings.database.path = Path("sift.db")
    assert settings.database.on_mounted_volume() is False

    # An absolute path inside the app directory is still ephemeral (negative control).
    settings.database.path = Path.cwd() / "sift.db"
    assert settings.database.on_mounted_volume() is False

    # A mounted volume: absolute and outside the app directory.
    settings.database.path = Path("/data/sift.db")
    assert settings.database.on_mounted_volume() is True

    # Postgres is never "a mounted volume" — it has its own persistence story.
    settings.database.url = "postgresql://u:p@host/db"
    assert settings.database.on_mounted_volume() is False


def test_section_overrides_survive_a_save(factory, settings):
    """The mapping is what keeps Home Videos out of the film library, so it has
    to persist like any other connection setting."""
    from sift.services import config_store

    with factory() as session:
        config_store.set_config(
            session, {"plex": {"section_kinds": {"Cartoons": "show", "Home Videos": "ignore"}}}
        )
        stored = config_store.get_config(session)
    assert stored["plex"]["section_kinds"]["Home Videos"] == "ignore"

    effective = config_store.apply_to_settings(settings, stored)
    assert effective.plex.section_kinds["Cartoons"] == "show"


def test_a_nonsense_section_kind_is_dropped_on_the_way_in(factory, settings):
    """NEGATIVE CONTROL: an unknown value must not reach the planner, where it
    would fall through to 'unknown type' and silently drop the library."""
    from sift.services import config_store

    with factory() as session:
        config_store.set_config(session, {"plex": {"section_kinds": {"Movies": "banana"}}})
        stored = config_store.get_config(session)
    effective = config_store.apply_to_settings(settings, stored)
    assert "Movies" not in effective.plex.section_kinds


def test_a_key_that_no_longer_decrypts_is_reported_rather_than_hidden(factory, monkeypatch):
    """"Why are my keys not being saved?" — because they were, and then the key
    that opens them changed.

    `get_config` turns an unopenable secret into `None`, and every consumer reads
    that as "not configured". That is right for the consumer and a silent lie to
    the owner: the field shows empty, exactly as if the save had failed. Rotating
    `SIFT_SECRET_KEY` does it, and so does rotating `SIFT_SERVER__API_TOKEN` on an
    instance where no separate secret key is set and the token is doing that job.
    """
    from sift.services import config_store, secretbox

    secretbox.configure("first-key-material")
    with factory() as session:
        config_store.set_config(session, {"radarr": {"api_key": "RADARR-KEY"}})
        assert config_store.masked(config_store.get_config(session))["radarr"]["api_key_set"]
        assert config_store.unreadable_secrets(session) == {}

    # The key is rotated. The stored value is now ciphertext nobody can open.
    secretbox.configure("second-key-material")
    with factory() as session:
        assert config_store.get_config(session)["radarr"]["api_key"] is None
        assert config_store.unreadable_secrets(session) == {"radarr": ["api_key"]}


def test_re_entering_the_key_clears_the_warning(factory, monkeypatch):
    """NEGATIVE CONTROL: the report has to go away when the problem does.

    A warning that stays up after the owner has done the one thing that fixes it
    is worse than no warning — it teaches them to ignore the banner.
    """
    from sift.services import config_store, secretbox

    secretbox.configure("first-key-material")
    with factory() as session:
        config_store.set_config(session, {"radarr": {"api_key": "RADARR-KEY"}})

    secretbox.configure("second-key-material")
    with factory() as session:
        assert config_store.unreadable_secrets(session)
        config_store.set_config(session, {"radarr": {"api_key": "RADARR-KEY-AGAIN"}})
        assert config_store.unreadable_secrets(session) == {}
        assert config_store.get_config(session)["radarr"]["api_key"] == "RADARR-KEY-AGAIN"


def test_a_never_entered_key_is_not_reported_as_lost(factory):
    """NEGATIVE CONTROL: nothing stored means nothing to warn about.

    Reporting every empty field as unreadable would put a permanent banner on a
    fresh install.
    """
    from sift.services import config_store, secretbox

    secretbox.configure("some-key-material")
    with factory() as session:
        config_store.set_config(session, {"radarr": {"base_url": "http://radarr:7878"}})
        assert config_store.unreadable_secrets(session) == {}
