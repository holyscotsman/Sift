"""Two Settings endpoints that exist to degrade well rather than to succeed.

`/api/settings/radarr_options` offers real root folders and quality profiles so
the add defaults are a choice rather than a guess. Every failure path in it
returns *empty* — unconfigured, unreachable, misconfigured — because the UI reads
empty as "defaults apply" and a 500 there would break a Settings page somebody is
visiting precisely because their connection is broken.

`/api/settings/test/{service}` probes live and then drops the cached health
sweep. That second half is the one worth guarding: without it the health dots keep
showing the old state for up to fifteen seconds after a successful test, which is
confusing at exactly the moment someone is debugging a connection and watching
them.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sift.config import RadarrConfig
from sift.db.session import init_db, make_engine, make_session_factory
from sift.main import create_app
from sift.services import auth


@pytest.fixture
def app_client(tmp_path, settings):
    def build(**radarr):
        engine = make_engine(tmp_path / f"s{len(radarr)}{radarr.get('enabled')}.db")
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            auth.create_account(session, "owner", "hunter2hunter2")
            token = auth.issue_token(
                auth._signing_secret(auth.get_auth(session)) or "", "owner"
            )
        if radarr:
            settings.radarr = RadarrConfig(**radarr)
        app = create_app(settings, session_factory=factory)
        client = TestClient(app)
        client.headers.update({"Authorization": f"Bearer {token}"})
        return client

    return build


def test_radarr_options_are_empty_when_radarr_is_not_configured(app_client):
    """Two things make this safe and only one of them is the early return.

    Deleting the `not enabled` shortcut leaves this green — the call falls through
    to `RadarrClient(...)`, which raises `ClientError` for a missing base URL, and
    that is caught a few lines below. Verified by mutation. The shortcut is an
    optimisation that avoids building a client at all, not the guard, and this
    test covers the behaviour rather than the line.
    """
    with app_client(enabled=False) as c:
        resp = c.get("/api/settings/radarr_options")

    assert resp.status_code == 200
    body = resp.json()
    assert body["root_folders"] == []
    assert body["quality_profiles"] == []


def test_radarr_options_are_empty_when_radarr_cannot_be_reached(app_client, monkeypatch):
    """The common case: Radarr is configured and the box is off. A Settings page
    that 500s here is a Settings page you cannot use to fix the problem."""
    from sift.clients import radarr as radarr_module

    original = radarr_module.RadarrClient.__init__

    def patched(self, config, **kwargs):
        def dead(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        original(self, config, transport=httpx.MockTransport(dead), **kwargs)

    monkeypatch.setattr(radarr_module.RadarrClient, "__init__", patched)

    with app_client(enabled=True, base_url="http://radarr.test:7878", api_key="k") as c:
        resp = c.get("/api/settings/radarr_options")

    assert resp.status_code == 200
    body = resp.json()
    assert body["root_folders"] == []
    assert body["quality_profiles"] == []


def test_NEGATIVE_CONTROL_a_reachable_radarr_offers_its_real_choices(app_client, monkeypatch):
    """Without this the tests above pass on an endpoint that returns empty always,
    which is the failure mode of every graceful-degradation test."""
    from sift.clients import radarr as radarr_module

    original = radarr_module.RadarrClient.__init__

    def patched(self, config, **kwargs):
        def answer(request: httpx.Request) -> httpx.Response:
            if "rootfolder" in request.url.path:
                return httpx.Response(200, json=[{"path": "/films"}, {"path": "/kids"}])
            return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}])

        original(self, config, transport=httpx.MockTransport(answer), **kwargs)

    monkeypatch.setattr(radarr_module.RadarrClient, "__init__", patched)

    with app_client(enabled=True, base_url="http://radarr.test:7878", api_key="k") as c:
        body = c.get("/api/settings/radarr_options").json()

    assert body["root_folders"] == ["/films", "/kids"]
    assert body["quality_profiles"] == [{"id": 4, "name": "HD-1080p"}]


def test_testing_a_connection_clears_the_cached_health_sweep(app_client):
    """The dots poll a 15-second cache. Someone who has just fixed a URL and
    pressed Test is watching those dots, and a stale sweep tells them the fix did
    not work."""
    with app_client(enabled=False) as c:
        # Prime the cache.
        assert c.get("/api/health").status_code == 200
        cache = c.app.state.sift.health_cache
        assert cache._value is not None

        assert c.post("/api/settings/test/radarr").status_code == 200

        assert cache._value is None, "the cached sweep survived a live test"


def test_testing_an_unknown_service_is_a_404(app_client):
    with app_client(enabled=False) as c:
        assert c.post("/api/settings/test/nonsense").status_code == 404
