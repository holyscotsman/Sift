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
from weakref import WeakKeyDictionary

from sqlalchemy.orm import Session

from ..db.models import Setting
from . import secretbox

_AUTH_KEY = "auth"
_PBKDF2_ROUNDS = 240_000
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# Asset tokens live in URLs — an <img> or a download link cannot send a header —
# and a URL is recorded by every proxy and access log it passes through, kept in
# browser history, and stored by shared caches. A thirty-day full-API credential
# has no business being there. These are minutes long and read-only, so a leaked
# log yields something already expired that could only ever fetch a thumbnail.
_ASSET_TTL_SECONDS = 15 * 60

SCOPE_SESSION = "session"
SCOPE_ASSET = "asset"


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


# ------------------------------------------------------------------- the auth row

# How long a cached auth row may be trusted without re-reading it.
#
# The cache is invalidated explicitly by every writer, so this is a backstop
# rather than the mechanism — it bounds the damage if a row is changed outside
# the app (a direct SQL edit, a restore from backup) or by a second worker.
# Thirty seconds is short enough that "I changed my password" is true almost
# immediately and long enough that a page polling every twenty seconds pays for
# at most one read per poll instead of two per request.
_CACHE_TTL_SECONDS = 30.0

# Keyed by database, not global. The tests build a fresh SQLite file per test in
# one process, so a single module-level slot would hand one test the previous
# test's account — and it would be wrong in production too if an instance ever
# addressed two databases.
#
# Keyed on the *engine object*, not on its URL string. A URL would work — SQLAlchemy
# renders the password as ``***`` in ``str()``, so nothing secret would land here —
# but it invites the question every time someone reads this, and two engines
# differing only by password would collide. A weak key sidesteps both, and empties
# itself when the engine is collected rather than accumulating one entry per
# database for the life of the process.
_auth_cache: WeakKeyDictionary[Any, tuple[float, dict[str, Any] | None]] = WeakKeyDictionary()


def _cache_key(session: Session) -> Any:
    """The engine this session talks to.

    ``get_bind`` returns a Connection instead of an Engine under some
    configurations; this codebase always binds to an Engine, and the fallback is
    harmless either way — a per-connection key makes the cache less effective, not
    incorrect.
    """
    return session.get_bind()


def invalidate_cache(session: Session | None = None) -> None:
    """Forget the cached auth row. **Every writer must call this.**

    Not optional and not a nicety: ``change_password`` rotates the signing secret
    precisely so that other sessions stop working, and a cache that kept serving
    the old secret would leave a suspected intruder signed in — which is the one
    thing that function exists to prevent. ``test_auth_cache`` enumerates the
    writers and fails the build when a new one forgets.

    With no session, clears every database's entry. That is what a factory reset
    wants, since it deletes the row out from under the cache by table.
    """
    if session is None:
        _auth_cache.clear()
    else:
        _auth_cache.pop(_cache_key(session), None)


def get_auth(session: Session) -> dict[str, Any] | None:
    """The stored account row, cached in memory between writes.

    Every gated request needs this twice — once to ask whether an account exists
    and once to verify the token's signature — and it was two round trips on
    hosted Postgres, on every poster, every page of an endless list, and every
    twenty-second health poll. Nothing in it changes except when the owner changes
    it, and each of those paths invalidates the cache.

    A copy is returned rather than the cached dict, so a caller mutating what it
    got back cannot rewrite what the next request will read.
    """
    key = _cache_key(session)
    hit = _auth_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < _CACHE_TTL_SECONDS:
        return dict(hit[1]) if hit[1] else None
    row = session.get(Setting, _AUTH_KEY)
    value = dict(row.value) if row and row.value else None
    _auth_cache[key] = (time.monotonic(), value)
    return dict(value) if value else None


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
    """The single write path for the auth row. Invalidates the read cache."""
    session.merge(Setting(key=_AUTH_KEY, value=auth))
    session.commit()
    invalidate_cache(session)


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
    # Unconditional: a cache holding an account the database no longer has is
    # exactly the state this must not leave behind, and the row being absent now
    # says nothing about what was cached a moment ago.
    invalidate_cache(session)


def change_password(session: Session, current: str, new: str) -> str | None:
    """Verify the current password, store a new hash, and **rotate the signing
    secret**. Returns a fresh token for the caller, or ``None`` if the current
    password doesn't match.

    Rotating is the point. Tokens live for thirty days, and the reason anyone
    changes a password on a publicly reachable instance is that they think someone
    else has access — which, without rotation, this did nothing whatsoever about.

    The caller gets a new token back, so only *other* sessions are signed out. The
    old behaviour kept every session alive to avoid logging the owner out of their
    own device; handing that device a replacement gets the same result without
    leaving a suspected intruder signed in.
    """
    auth = get_auth(session)
    if not auth or not verify_password(current, auth.get("password_hash", "")):
        return None
    secret = secrets.token_hex(32)
    # Through ``_store``, not a bare merge: that is where the cache is dropped,
    # and a rotation the cache did not hear about would leave every other session
    # working — the precise opposite of what rotating is for.
    _store(
        session,
        {
            **auth,
            "password_hash": hash_password(new),
            "secret": secretbox.encrypt(secret),
        },
    )
    return issue_token(secret, str(auth.get("username", "")))


# ------------------------------------------------------------------ session token


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(
    secret: str,
    username: str,
    *,
    now: float | None = None,
    scope: str = SCOPE_SESSION,
) -> str:
    ts = int(time.time() if now is None else now)
    ttl = _ASSET_TTL_SECONDS if scope == SCOPE_ASSET else _TOKEN_TTL_SECONDS
    body = {"u": username, "iat": ts, "exp": ts + ttl, "s": scope}
    payload = _b64e(json.dumps(body).encode())
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(
    secret: str,
    token: str,
    *,
    now: float | None = None,
    scopes: tuple[str, ...] = (SCOPE_SESSION,),
) -> str | None:
    """Return the username if the token is well-formed, signed, unexpired and in scope.

    Scope is checked here rather than at the call site so it cannot be forgotten
    at one. A token minted for asset URLs must never open the rest of the API,
    which is the entire reason for minting a separate one.

    Tokens issued before scopes existed carry no ``s`` field and are treated as
    session tokens, so nobody is logged out by this change.
    """
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
    if str(payload.get("s") or SCOPE_SESSION) not in scopes:
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


def token_valid(
    session: Session,
    token: str,
    *,
    now: float | None = None,
    scopes: tuple[str, ...] = (SCOPE_SESSION,),
) -> bool:
    auth = get_auth(session)
    if not auth or not token:
        return False
    secret = _signing_secret(auth)
    if not secret:
        return False  # unreadable secret → no token can be trusted
    return verify_token(secret, token, now=now, scopes=scopes) is not None


def issue_asset_token(session: Session, *, now: float | None = None) -> tuple[str, int] | None:
    """A short-lived, read-only token for URLs that cannot carry a header.

    Returns ``(token, seconds_valid)``, or ``None`` when no account exists.
    """
    auth = get_auth(session)
    if not auth:
        return None
    secret = _signing_secret(auth)
    username = auth.get("username")
    if not secret or not isinstance(username, str):
        return None
    return (
        issue_token(secret, username, now=now, scope=SCOPE_ASSET),
        _ASSET_TTL_SECONDS,
    )
