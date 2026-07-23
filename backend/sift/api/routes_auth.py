"""Authentication: setup-status, first-run account creation, and login.

These endpoints are intentionally NOT behind the API gate — they are the way in.
``setup`` only works while no account exists (first run); afterwards it's a 409 and
credentials can only change via a logged-in reset. ``login`` returns a session token
the client stores and sends like the access token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from ..services import auth
from ..services.ratelimit import LoginRateLimiter
from .deps import AuthDep, get_login_limiter, get_session_factory
from .schemas import (
    AuthStatus,
    ChangePasswordRequest,
    LoginRequest,
    OkResponse,
    SetupRequest,
    TokenResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
def status(factory: sessionmaker[Session] = Depends(get_session_factory)) -> AuthStatus:
    with factory() as session:
        configured = auth.is_configured(session)
        username = (auth.get_auth(session) or {}).get("username") if configured else None
    return AuthStatus(setup_complete=configured, username=username)


@router.post("/setup", response_model=TokenResponse, status_code=201)
def setup(
    body: SetupRequest, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> TokenResponse:
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


@router.post("/password", response_model=OkResponse, dependencies=[AuthDep])
def change_password(
    body: ChangePasswordRequest,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> OkResponse:
    """Change the password without a factory reset. Gated (must be signed in) AND
    re-verifies the current password; existing sessions stay valid."""
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    with factory() as session:
        if not auth.change_password(session, body.current_password, body.new_password):
            raise HTTPException(status_code=401, detail="current password is wrong")
    return OkResponse(ok=True)
