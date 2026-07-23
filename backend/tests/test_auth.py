"""Username/password auth: hashing, signed tokens, and the gate lifecycle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.main import create_app
from sift.services import auth

# ----------------------------------------------------------------- unit: crypto


def test_password_hash_roundtrip_and_reject():
    h = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", h)
    assert not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", "not-a-valid-hash")


def test_token_sign_verify_and_tamper():
    tok = auth.issue_token("s3cret", "alice", now=1000.0)
    assert auth.verify_token("s3cret", tok, now=1000.0) == "alice"
    # Wrong secret, tampered signature, and expiry all reject.
    assert auth.verify_token("other", tok, now=1000.0) is None
    assert auth.verify_token("s3cret", tok + "x", now=1000.0) is None
    assert auth.verify_token("s3cret", tok, now=1000.0 + 60 * 60 * 24 * 365) is None


def test_account_lifecycle(factory):
    with factory() as session:
        assert not auth.is_configured(session)
        auth.create_account(session, "alice", "hunter2hunter2")
        assert auth.is_configured(session)
        assert auth.login(session, "alice", "hunter2hunter2") is not None
        assert auth.login(session, "alice", "nope") is None
        assert auth.login(session, "bob", "hunter2hunter2") is None


# --------------------------------------------------------------- endpoint gate


@pytest.fixture
def client(settings, factory):
    settings.server.api_token = None  # no static token — auth is via account only
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c


def _setup(client, username="alice", password="hunter2hunter2"):
    return client.post("/api/auth/setup", json={"username": username, "password": password})


def _login(client, username="alice", password="hunter2hunter2"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_gate_open_before_setup_then_closes(client):
    # Fresh install: API is open so the wizard is reachable.
    assert client.get("/api/auth/status").json() == {"setup_complete": False, "username": None}
    assert client.get("/api/status").status_code == 200

    # Create the account.
    r = _setup(client)
    assert r.status_code == 201
    token = r.json()["token"]
    assert r.json()["username"] == "alice"

    # Now the gate is closed to unauthenticated calls.
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"X-Sift-Token": token}).status_code == 200
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/status", headers=bearer).status_code == 200

    # Status now reports configured.
    assert client.get("/api/auth/status").json()["setup_complete"] is True


def test_setup_twice_conflicts(client):
    assert _setup(client).status_code == 201
    assert _setup(client, "eve", "password9999").status_code == 409


def test_setup_validates_length(client):
    assert _setup(client, "ab").status_code == 422
    assert _setup(client, "alice", "short").status_code == 422


def test_login_after_setup(client):
    _setup(client)
    assert _login(client, password="wrong").status_code == 401
    ok = _login(client)
    assert ok.status_code == 200
    token = ok.json()["token"]
    assert client.get("/api/status", headers={"X-Sift-Token": token}).status_code == 200


def test_poster_accepts_session_token(client):
    token = _setup(client).json()["token"]
    # No token → gated; a valid session token via ?token= gets past the gate (then 404
    # because sources are disabled, so no poster resolves — proving auth, not artwork).
    assert client.get("/api/poster/603").status_code == 401
    assert client.get(f"/api/poster/603?token={token}").status_code == 404


def test_scan_ws_accepts_session_token(client):
    from starlette.websockets import WebSocketDisconnect

    token = _setup(client).json()["token"]
    # A bad token is rejected (server closes before accept).
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/scan/1?token=wrong-token"):
            pass
    # The login session token is accepted — the connection opens (this used to fail:
    # the WS only honoured the static API token, so progress dropped for logged-in users).
    with client.websocket_connect(f"/ws/scan/1?token={token}"):
        pass


def test_change_password_full_lifecycle(client):
    token = _setup(client).json()["token"]
    headers = {"X-Sift-Token": token}

    # Wrong current password → 401; too-short new password → 422.
    bad = client.post(
        "/api/auth/password",
        json={"current_password": "nope", "new_password": "longenough1"},
        headers=headers,
    )
    assert bad.status_code == 401
    short = client.post(
        "/api/auth/password",
        json={"current_password": "hunter2hunter2", "new_password": "short"},
        headers=headers,
    )
    assert short.status_code == 422

    ok = client.post(
        "/api/auth/password",
        json={"current_password": "hunter2hunter2", "new_password": "brand-new-pass-9"},
        headers=headers,
    )
    assert ok.status_code == 200

    # Old password dead, new password lives, existing session token still valid
    # (the signing secret is kept on purpose).
    assert _login(client).status_code == 401
    assert _login(client, password="brand-new-pass-9").status_code == 200
    assert client.get("/api/status", headers=headers).status_code == 200


def test_change_password_requires_auth(client):
    _setup(client)
    r = client.post(
        "/api/auth/password",
        json={"current_password": "hunter2hunter2", "new_password": "longenough1"},
    )
    assert r.status_code == 401
