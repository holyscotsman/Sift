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
