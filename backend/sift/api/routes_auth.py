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
from .deps import get_session_factory
from .schemas import AuthStatus, LoginRequest, SetupRequest, TokenResponse

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
    assert token is not None  # just created
    return TokenResponse(token=token, username=username)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, factory: sessionmaker[Session] = Depends(get_session_factory)
) -> TokenResponse:
    with factory() as session:
        token = auth.login(session, body.username.strip(), body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="invalid username or password")
    return TokenResponse(token=token, username=body.username.strip())
