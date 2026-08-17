"""Authentication: setup-status, first-run account creation, and login.

These endpoints are intentionally NOT behind the API gate — they are the way in.
``setup`` only works while no account exists (first run); afterwards it's a 409 and
credentials can only change via a logged-in reset. ``login`` returns a session token
the client stores and sends like the access token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from ..services import auth
from ..services.ratelimit import LoginRateLimiter
from .deps import (
    AuthDep,
    get_login_limiter,
    get_session_factory,
    get_state,
    presented_token,
    token_accepted,
)
from .schemas import (
    AuthStatus,
    ChangePasswordRequest,
    LoginRequest,
    SetupRequest,
    TokenResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
def status(
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> AuthStatus:
    with factory() as session:
        configured = auth.is_configured(session)
        # The username is returned only to a caller who already holds a valid
        # credential. Login refuses on an unknown username before it ever checks
        # the password, and the rate limiter is keyed by username — so handing
        # the real one to anonymous callers turns a two-dimensional guess into a
        # one-dimensional one. The sign-in screen needs `setup_complete` alone;
        # it prefills the name from its own local storage.
        known = configured and token_accepted(
            get_state(request), presented_token(authorization, x_sift_token)
        )
        username = (auth.get_auth(session) or {}).get("username") if known else None
    return AuthStatus(setup_complete=configured, username=username)


@router.post("/setup", response_model=TokenResponse, status_code=201)
def setup(
    request: Request,
    body: SetupRequest,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> TokenResponse:
    # The only guard used to be "no account exists yet", which is a window rather
    # than a wall: anyone who reached the hostname first got the account, and the
    # owner got a 409. Worse, the window reopens every time the settings table is
    # empty on boot. Where a static server token is configured — the hosted
    # Blueprint generates one — creating the account now requires it, so the
    # first-runner has to be somebody holding a deploy credential.
    state = get_state(request)
    static = state.settings.server.api_token
    if static and not token_accepted(state, presented_token(authorization, x_sift_token)):
        raise HTTPException(status_code=401, detail="setup requires the server access token")
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=422, detail="username must be at least 3 characters")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    with factory() as session:
        if auth.is_configured(session):
            raise HTTPException(status_code=409, detail="already set up — sign in instead")
        auth.create_account(session, username, body.password)
        token = auth.login(session, username, body.password)
    if token is None:  # unreachable: the account was just created
        raise HTTPException(status_code=500, detail="account creation failed")
    return TokenResponse(token=token, username=username)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    factory: sessionmaker[Session] = Depends(get_session_factory),
    limiter: LoginRateLimiter = Depends(get_login_limiter),
) -> TokenResponse:
    username = body.username.strip()
    # Brute-force guard: repeated failures for the same account back off before
    # the password is even checked. A success clears the window.
    wait = limiter.retry_after(username)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="too many failed attempts — try again shortly",
            headers={"Retry-After": str(wait)},
        )
    with factory() as session:
        token = auth.login(session, username, body.password)
    if token is None:
        limiter.record_failure(username)
        raise HTTPException(status_code=401, detail="invalid username or password")
    limiter.record_success(username)
    return TokenResponse(token=token, username=username)


@router.post("/password", response_model=TokenResponse, dependencies=[AuthDep])
def change_password(
    body: ChangePasswordRequest,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> TokenResponse:
    """Change the password without a factory reset. Gated (must be signed in) AND
    re-verifies the current password.

    Returns a **new token**: changing the password rotates the signing secret, so
    every other session is signed out. Store the returned token or this device
    signs itself out too.
    """
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    with factory() as session:
        token = auth.change_password(session, body.current_password, body.new_password)
        if token is None:
            raise HTTPException(status_code=401, detail="current password is wrong")
        username = str((auth.get_auth(session) or {}).get("username", ""))
    return TokenResponse(token=token, username=username)
