"""Single-user username/password auth for a hosted Sift.

Passwords are PBKDF2-HMAC-SHA256 with a per-password salt; the login credential and
a per-instance signing secret live in the ``settings`` table (key ``auth``). Sessions
are stateless signed tokens (HMAC over a small JSON payload), so there's no session
store to keep or expire.

The signing secret is **encrypted at rest** (:mod:`sift.services.secretbox`). It has
to be: in the clear it turns a database dump into a forged session, and an
authenticated attacker can make the app decrypt every other stored credential for
them — which would leave the connection-key encryption doing nothing useful. If the
encryption key changes the secret becomes unreadable; that logs everyone out but
cannot lock the owner out, because ``login`` verifies against the password hash
(independent of this secret) and then mints a replacement.

The token is sent exactly like the existing access token (``X-Sift-Token`` /
``Authorization: Bearer``), so the gate accepts either a valid session token or the
static ``SIFT_SERVER__API_TOKEN`` (kept for env-configured deploys).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Setting
from . import secretbox

_AUTH_KEY = "auth"
_PBKDF2_ROUNDS = 240_000
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


# ---------------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, rounds_s, salt_hex, hash_hex = stored.split("$")
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return hmac.compare_digest(dk, expected)


# ------------------------------------------------------------------- credentials


def get_auth(session: Session) -> dict[str, Any] | None:
    row = session.get(Setting, _AUTH_KEY)
    return dict(row.value) if row and row.value else None


def is_configured(session: Session) -> bool:
    auth = get_auth(session)
    return bool(auth and auth.get("username") and auth.get("password_hash"))


def _signing_secret(auth: dict[str, Any]) -> str | None:
    """The session-signing secret in usable form, or None when it can't be read.

    Stored encrypted: it is the one value in this table that turns a database dump
    into a forged admin session, which would in turn let an attacker read back every
    other credential through the running app. Encrypting the connection keys without
    this one would be theatre.
    """
    stored = auth.get("secret")
    return secretbox.decrypt(stored) if isinstance(stored, str) and stored else None


def _store(session: Session, auth: dict[str, Any]) -> None:
    session.merge(Setting(key=_AUTH_KEY, value=auth))
    session.commit()


def create_account(session: Session, username: str, password: str) -> None:
    """Create (or overwrite) the single account. Mints a fresh signing secret, which
    invalidates any previously issued tokens."""
    _store(
        session,
        {
            "username": username,
            "password_hash": hash_password(password),
            "secret": secretbox.encrypt(secrets.token_hex(32)),
        },
    )


def upgrade_stored_secret(session: Session) -> bool:
    """Seal (or re-seal) the signing secret at boot, mirroring the connections
    upgrade. Non-destructive: a secret that can't be opened at all is left alone —
    ``login`` re-mints it rather than this silently discarding it."""
    auth = get_auth(session)
    if not auth or not secretbox.needs_resealing(auth.get("secret")):
        return False
    _store(session, {**auth, "secret": secretbox.reseal(str(auth["secret"]))})
    return True


def clear_account(session: Session) -> None:
    row = session.get(Setting, _AUTH_KEY)
    if row is not None:
        session.delete(row)
        session.commit()


def change_password(session: Session, current: str, new: str) -> bool:
    """Verify the current password and store a new hash. The signing secret is
    kept, so existing sessions (this device included) stay signed in. Returns
    False when the current password doesn't match."""
    auth = get_auth(session)
    if not auth or not verify_password(current, auth.get("password_hash", "")):
        return False
    session.merge(Setting(key=_AUTH_KEY, value={**auth, "password_hash": hash_password(new)}))
    session.commit()
    return True


# ------------------------------------------------------------------ session token


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(secret: str, username: str, *, now: float | None = None) -> str:
    ts = int(time.time() if now is None else now)
    payload = _b64e(json.dumps({"u": username, "iat": ts, "exp": ts + _TOKEN_TTL_SECONDS}).encode())
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str, *, now: float | None = None) -> str | None:
    """Return the username if the token is well-formed, correctly signed, and unexpired."""
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = payload.get("exp", 0)
    if not isinstance(exp, int | float) or exp < (time.time() if now is None else now):
        return None
    username = payload.get("u")
    return username if isinstance(username, str) else None


def login(
    session: Session, username: str, password: str, *, now: float | None = None
) -> str | None:
    """Return a session token on success, else None."""
    auth = get_auth(session)
    if not auth:
        return None
    if username != auth.get("username"):
        return None
    if not verify_password(password, auth.get("password_hash", "")):
        return None
    secret = _signing_secret(auth)
    if secret is None:
        # The encryption key changed (or went missing), so the stored secret can't be
        # read. The password just verified against its own independent hash, so this
        # is recoverable: mint a fresh secret rather than lock the owner out of their
        # own instance. Any previously issued token stops working, which is correct.
        secret = secrets.token_hex(32)
        _store(session, {**auth, "secret": secretbox.encrypt(secret)})
    return issue_token(secret, username, now=now)


def token_valid(session: Session, token: str, *, now: float | None = None) -> bool:
    auth = get_auth(session)
    if not auth or not token:
        return False
    secret = _signing_secret(auth)
    if not secret:
        return False  # unreadable secret → no token can be trusted
    return verify_token(secret, token, now=now) is not None
