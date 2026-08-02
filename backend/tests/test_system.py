"""Restart and update — both hand control to the host, so the tests pin that they
never do anything drastic themselves."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.main import create_app
from sift.services import config_store


@pytest.fixture
def client(settings, factory):
    settings.server.api_token = None
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        token = c.post(
            "/api/auth/setup", json={"username": "alice", "password": "hunter2hunter2"}
        ).json()["token"]
        c.headers.update({"X-Sift-Token": token})
        yield c


def test_restart_schedules_an_exit_rather_than_killing_the_process(client, monkeypatch):
    """The response must reach the browser before the process goes away, so the
    exit is scheduled, not immediate. If this ever became a direct os._exit the
    test process itself would die — which is the point of pinning it."""
    from sift.api import routes_system

    fired: list[bool] = []
    monkeypatch.setattr(routes_system, "_terminate", lambda: fired.append(True))
    r = client.post("/api/system/restart")
    # The response comes back first — the exit is deferred, so the browser gets a
    # confirmation instead of a dropped connection.
    assert r.status_code == 200 and r.json()["ok"] is True
    assert routes_system._EXIT_DELAY_SECONDS > 0
    assert fired == []  # not yet: it is scheduled, not immediate


def test_restart_says_so_when_nothing_will_bring_it_back(client, monkeypatch):
    """A bare local run has no supervisor, so 'restart' really means 'stop'. Saying
    otherwise would strand someone with a dead app and no explanation."""
    from sift.api import routes_system

    monkeypatch.setattr(routes_system, "_terminate", lambda: None)
    for var in ("RENDER", "FLY_APP_NAME", "RAILWAY_ENVIRONMENT", "KOYEB_APP_NAME"):
        monkeypatch.delenv(var, raising=False)
    body = client.post("/api/system/restart").json()
    assert body["supervised"] is False
    assert "start it again yourself" in body["detail"]

    monkeypatch.setenv("RENDER", "true")
    body = client.post("/api/system/restart").json()
    assert body["supervised"] is True
    assert "host will bring Sift back" in body["detail"]


def test_update_without_a_hook_explains_where_to_get_one(client):
    """NEGATIVE CONTROL: no hook must be an actionable 400, not a silent no-op that
    looks like the update ran."""
    r = client.post("/api/system/update")
    assert r.status_code == 400
    assert "Deploy Hook" in r.json()["detail"]


def test_update_posts_to_the_configured_hook(client, factory, monkeypatch):
    import httpx

    from sift.api import routes_system

    with factory() as session:
        config_store.set_config(session, {"deploy": {"hook_url": "https://hook.test/deploy"}})

    called: list[str] = []

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url):
            called.append(url)
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(routes_system.httpx, "AsyncClient", FakeClient)
    r = client.post("/api/system/update")
    assert r.status_code == 200 and called == ["https://hook.test/deploy"]


def test_the_deploy_hook_is_stored_encrypted(factory):
    """It's a secret URL — anyone holding it can trigger a deploy — so it must be
    sealed like an API key, not left readable in the database."""
    from sift.db.models import Setting
    from sift.services import secretbox

    secretbox.configure("deploy-token")
    try:
        with factory() as session:
            config_store.set_config(session, {"deploy": {"hook_url": "https://hook.test/x"}})
        with factory() as session:
            raw = dict(session.get(Setting, "connections").value)
            assert secretbox.is_encrypted(raw["deploy"]["hook_url"])
            assert "hook.test" not in str(raw)
            # ...and still usable by the app.
            assert config_store.get_config(session)["deploy"]["hook_url"] == "https://hook.test/x"
            # Masked view never leaks it to the browser.
            masked = config_store.masked(config_store.get_config(session))
            assert masked["deploy"] == {"hook_url_set": True}
    finally:
        secretbox.configure(None)


# --------------------------------------------------------------- version checking


def test_versions_compare_numerically_not_as_strings():
    """The bug a string compare would cause: "2607.9.0" > "2607.14.0" is True
    alphabetically, so an up-to-date instance would nag forever."""
    from sift.services import updates

    assert updates.is_newer("2607.14.0", "2607.9.0") is True
    assert updates.is_newer("2607.9.0", "2607.14.0") is False
    assert updates.is_newer("2607.14.0", "2607.14.0") is False  # equal is not newer
    # A hand-edited or odd version must not raise.
    assert updates.version_tuple("2607.14.0-dev") == (2607, 14, 0)
    assert updates.version_tuple("weird") == (0,)


async def test_a_failed_update_check_reports_unknown_not_up_to_date(monkeypatch):
    """NEGATIVE CONTROL: offline must be 'couldn't check'. Reporting 'up to date'
    when you don't know is the one answer that actively misleads."""
    from sift.services import updates

    updates.reset_cache()

    class Boom:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise RuntimeError("no network")

    monkeypatch.setattr(updates.httpx, "AsyncClient", Boom)
    assert await updates.latest_version(force=True) is None
    updates.reset_cache()


def test_the_published_version_is_parsed_from_pyproject():
    from sift.services import updates

    assert updates._parse_version('name = "sift"\nversion = "2607.15.0"\n') == "2607.15.0"
    assert updates._parse_version("no version here") is None


async def test_version_endpoint_reports_running_and_update_availability(client, monkeypatch):
    from sift.services import updates

    updates.reset_cache()

    async def fake_latest(**_kw):
        return "9999.1.0"

    monkeypatch.setattr(updates, "latest_version", fake_latest)
    body = client.get("/api/system/version").json()
    assert body["running"]  # whatever this build is
    assert body["latest"] == "9999.1.0"
    assert body["update_available"] is True
    # No deploy hook configured in this fixture, so Update can't act on it — the
    # UI needs to know that rather than offering a button that will 400.
    assert body["can_update"] is False
    updates.reset_cache()
