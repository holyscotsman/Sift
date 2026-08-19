"""Small hardening pins: what anonymous callers may learn, and where guards apply.

None of these is a compromise on its own. Each one shortens the distance between
"found the hostname" and "holding a credential", which on a single-user app whose
login page faces the internet is the whole of the attack surface.
"""

from __future__ import annotations

import hmac

import pytest
from fastapi.testclient import TestClient

from sift.api import deps
from sift.api.deps import AppState, token_accepted
from sift.clients.base import ClientError, reject_unsafe_base_url
from sift.main import create_app
from sift.services import auth


@pytest.fixture
def client(factory, settings) -> TestClient:
    return TestClient(create_app(settings, session_factory=factory))


def test_auth_status_withholds_the_username_from_anonymous_callers(
    client: TestClient, factory
) -> None:
    """Login refuses on an unknown username *before* it checks the password, and
    the rate limiter is keyed by username — so publishing the real one turns a
    two-dimensional guess into a one-dimensional one."""
    with factory() as session:
        auth.create_account(session, "owner", "correct-horse-battery")

    body = client.get("/api/auth/status").json()
    assert body["setup_complete"] is True
    assert body["username"] is None


def test_auth_status_still_tells_a_signed_in_caller_who_they_are(
    client: TestClient, factory
) -> None:
    """NEGATIVE CONTROL: withholding it from everybody would be a different bug.

    A caller holding a valid token still gets the username — Settings renders it.
    """
    with factory() as session:
        auth.create_account(session, "owner", "correct-horse-battery")
    token = client.post(
        "/api/auth/login", json={"username": "owner", "password": "correct-horse-battery"}
    ).json()["token"]

    body = client.get("/api/auth/status", headers={"X-Sift-Token": token}).json()
    assert body["username"] == "owner"


def test_auth_status_is_reachable_before_setup(client: TestClient) -> None:
    """NEGATIVE CONTROL: the endpoint is how the UI decides between the wizard and
    the sign-in form, so it must answer for an anonymous caller on a fresh
    install rather than 401."""
    body = client.get("/api/auth/status").json()
    assert body["setup_complete"] is False


def test_the_ollama_probe_refuses_the_metadata_host(client: TestClient, factory) -> None:
    """The link-local guard lives in BaseClient, and this probe builds its own
    HTTP client — so it was the one path that could be aimed at the cloud
    metadata service and used as a reachability oracle."""
    with factory() as session:
        auth.create_account(session, "owner", "correct-horse-battery")
    token = client.post(
        "/api/auth/login", json={"username": "owner", "password": "correct-horse-battery"}
    ).json()["token"]

    response = client.post(
        "/api/config/test/ollama",
        json={"values": {"base_url": "http://169.254.169.254"}},
        headers={"X-Sift-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_private_addresses_stay_allowed() -> None:
    """NEGATIVE CONTROL: the guard must not become a blanket private-range block.

    A local Ollama, Plex or Radarr lives at exactly these addresses; refusing
    them would make the app useless for its actual deployment.
    """
    for base in ("http://192.168.1.50:11434", "http://10.0.0.4:8096", "http://127.0.0.1:11434"):
        reject_unsafe_base_url("ollama", base)  # must not raise


def test_metadata_hosts_are_refused_by_the_shared_guard() -> None:
    for base in ("http://169.254.169.254", "http://metadata.google.internal"):
        with pytest.raises(ClientError):
            reject_unsafe_base_url("ollama", base)


def test_static_token_is_compared_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """`==` on str short-circuits at the first differing byte, which leaks the
    token one character at a time. Assert the call actually routes through
    compare_digest rather than trusting that it looks like it does."""
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a: object, b: object) -> bool:
        calls.append((str(a), str(b)))
        return real(a, b)  # type: ignore[arg-type]

    monkeypatch.setattr(deps.hmac, "compare_digest", spy)

    from pydantic import SecretStr

    from sift.config import load_settings

    settings = load_settings(config_path=None)
    settings.server.api_token = SecretStr("s3cret-token")
    state = AppState.__new__(AppState)
    object.__setattr__(state, "settings", settings)

    assert token_accepted(state, "s3cret-token") is True
    assert calls, "the static token was compared without hmac.compare_digest"


def test_setup_requires_the_server_token_when_one_is_configured(factory, settings) -> None:
    """The wizard was a window, not a wall: whoever reached the hostname first got
    the account, and the window reopened whenever the settings table was empty on
    boot. Where a deploy generates a static token, setup now needs it."""
    from pydantic import SecretStr

    settings.server.api_token = SecretStr("deploy-token")
    client = TestClient(create_app(settings, session_factory=factory))

    anon = client.post(
        "/api/auth/setup", json={"username": "attacker", "password": "long-enough-pw"}
    )
    assert anon.status_code == 401

    owner = client.post(
        "/api/auth/setup",
        json={"username": "owner", "password": "long-enough-pw"},
        headers={"X-Sift-Token": "deploy-token"},
    )
    assert owner.status_code == 201


def test_setup_stays_open_when_no_token_is_configured(client: TestClient) -> None:
    """NEGATIVE CONTROL: a local install with no static token must still be
    settable up from the browser, or the fix locks everyone out of first run."""
    response = client.post(
        "/api/auth/setup", json={"username": "owner", "password": "long-enough-pw"}
    )
    assert response.status_code == 201


def test_the_schema_is_not_served_anonymously(client: TestClient) -> None:
    """Every route, every request body and the exact build version, free to
    anyone who finds the hostname."""
    # Not a status assertion: with a built frontend present these paths fall
    # through to the SPA's index.html, which is a 200 and is fine. What must not
    # come back is the schema itself.
    for path in ("/openapi.json", "/docs", "/redoc"):
        body = client.get(path).text
        assert '"openapi"' not in body, path
        assert '"/api/agent/claim"' not in body, path
        assert "swagger-ui" not in body.lower(), path


def _signed_in(client: TestClient, factory) -> str:
    with factory() as session:
        auth.create_account(session, "owner", "correct-horse-battery")
    return str(
        client.post(
            "/api/auth/login", json={"username": "owner", "password": "correct-horse-battery"}
        ).json()["token"]
    )


def test_an_asset_token_cannot_open_the_api(client: TestClient, factory) -> None:
    """The whole point of minting a separate one.

    Posters, downloads and the scan socket carry their credential in the query
    string, because an <img>, a download link and a WebSocket cannot send a
    header. Query strings are recorded by every proxy they pass and kept in
    browser history — so what travels there must not be the thirty-day
    credential that opens the entire API.
    """
    session_token = _signed_in(client, factory)
    asset = client.get("/api/auth/asset-token", headers={"X-Sift-Token": session_token}).json()

    # It opens the asset route it was minted for...
    assert client.get(f"/api/poster/603?token={asset['token']}").status_code in (404, 200)
    # ...and nothing else.
    for path in ("/api/movies", "/api/status", "/api/config", "/api/activity"):
        assert (
            client.get(path, headers={"X-Sift-Token": asset["token"]}).status_code == 401
        ), path
    assert asset["expires_in"] <= 60 * 60


def test_the_session_token_still_opens_everything(client: TestClient, factory) -> None:
    """NEGATIVE CONTROL: scoping must not lock the real session out.

    A gate that refused both kinds would satisfy the test above and log the owner
    out of their own app.
    """
    session_token = _signed_in(client, factory)
    for path in ("/api/movies", "/api/status", "/api/config"):
        assert client.get(path, headers={"X-Sift-Token": session_token}).status_code == 200, path
    assert client.get(f"/api/poster/603?token={session_token}").status_code in (404, 200)


def test_an_asset_token_expires_quickly() -> None:
    """A leaked access log should yield something already dead."""
    from sift.services import auth as auth_service

    issued = auth_service.issue_token("secret", "owner", now=0, scope=auth_service.SCOPE_ASSET)
    assert auth_service.verify_token(
        "secret", issued, now=60, scopes=(auth_service.SCOPE_ASSET,)
    ) == "owner"
    # Well inside the thirty-day session lifetime, and long gone.
    assert (
        auth_service.verify_token(
            "secret", issued, now=60 * 60 * 24, scopes=(auth_service.SCOPE_ASSET,)
        )
        is None
    )


def test_tokens_issued_before_scopes_still_work() -> None:
    """NEGATIVE CONTROL: nobody is logged out by this change.

    A token minted before the scope field existed carries no `s` and must still
    read as a full session token rather than being rejected.
    """
    import base64
    import hashlib
    import hmac as _hmac
    import json

    from sift.services import auth as auth_service

    body = json.dumps({"u": "owner", "iat": 0, "exp": 10_000}).encode()
    payload = base64.urlsafe_b64encode(body).decode().rstrip("=")
    sig = _hmac.new(b"secret", payload.encode(), hashlib.sha256).hexdigest()
    legacy = f"{payload}.{sig}"

    assert auth_service.verify_token("secret", legacy, now=100) == "owner"


def test_a_refusing_database_says_so_rather_than_500(factory, settings) -> None:
    """A hosted database that stops accepting queries is not a bug in this app.

    A connection limit, a suspended compute or an exhausted free-tier allowance
    all arrive as the same exception, and all of them used to surface as bare
    "Internal Server Error" on one screen and a spinner that never resolved on
    another — indistinguishable, from the browser, from Sift being broken.
    """
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _refuse(*_a, **_kw):
        raise OperationalError("SELECT 1", {}, Exception("transfer allowance exceeded"))

    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/api/junk")
    finally:
        event.remove(engine, "before_cursor_execute", _refuse)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "database" in detail.lower()
    # And it must not blame Sift for something Sift did not do.
    assert "internal server error" not in detail.lower()


def test_a_healthy_database_is_not_reported_as_unavailable(factory, settings) -> None:
    """NEGATIVE CONTROL: a handler that caught everything would turn ordinary
    responses into 503s and make the app look permanently broken."""
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    with TestClient(create_app(settings, session_factory=factory)) as c:
        assert c.get("/api/junk").status_code == 200
        assert c.get("/api/status").status_code == 200


def test_the_wizard_is_told_the_deploy_token_is_needed(factory, settings) -> None:
    """Requiring the token without saying so locked the owner out of their own app.

    A hosted Blueprint generates ``SIFT_SERVER__API_TOKEN``, and setup refuses
    without it — correctly, or whoever finds the hostname first gets the account.
    But the browser had no way to learn that: the wizard posted a username and a
    password, got a 401 it could not explain, and there was no field to put the
    token in. On the deployment path this app is documented for, first run simply
    did not work.
    """
    from pydantic import SecretStr

    settings.server.api_token = SecretStr("deploy-token")
    client = TestClient(create_app(settings, session_factory=factory))

    body = client.get("/api/auth/status").json()
    assert body["setup_complete"] is False
    assert body["setup_requires_token"] is True


def test_a_local_install_is_not_asked_for_a_token_it_does_not_have(
    client: TestClient,
) -> None:
    """NEGATIVE CONTROL: a field nobody can fill in is worse than no field.

    With no static token configured, setup is open and the wizard must not
    demand a credential that does not exist.
    """
    body = client.get("/api/auth/status").json()
    assert body["setup_complete"] is False
    assert body["setup_requires_token"] is False


def test_a_finished_install_stops_advertising_setup(factory, settings) -> None:
    """NEGATIVE CONTROL: the flag describes first run, not the deploy.

    Once an account exists, setup is closed for good — reporting that it "needs a
    token" would tell an anonymous caller there is a way in that no longer exists.
    """
    from pydantic import SecretStr

    settings.server.api_token = SecretStr("deploy-token")
    client = TestClient(create_app(settings, session_factory=factory))
    client.post(
        "/api/auth/setup",
        json={"username": "owner", "password": "long-enough-pw"},
        headers={"X-Sift-Token": "deploy-token"},
    )

    body = client.get("/api/auth/status").json()
    assert body["setup_complete"] is True
    assert body["setup_requires_token"] is False
