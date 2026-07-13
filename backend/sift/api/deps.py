"""Shared FastAPI dependencies: app state accessors and API-token gating."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from ..actions.engine import ActionEngine
from ..config import Settings
from ..services.scanner import ProgressHub


@dataclass
class AppState:
    settings: Settings
    session_factory: sessionmaker[Session]
    engine: ActionEngine
    hub: ProgressHub


def get_state(request: Request) -> AppState:
    return request.app.state.sift  # type: ignore[no-any-return]


def get_settings(request: Request) -> Settings:
    return get_state(request).settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return get_state(request).session_factory


def get_action_engine(request: Request) -> ActionEngine:
    return get_state(request).engine


def _token_matches(configured: str, presented: str | None) -> bool:
    return presented is not None and presented == configured


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> None:
    """Enforce the API token when one is configured; no-op otherwise.

    Accepts either ``Authorization: Bearer <token>`` or ``X-Sift-Token: <token>``.
    """
    token = get_state(request).settings.server.api_token
    if token is None:
        return
    configured = token.get_secret_value()
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:]
    if _token_matches(configured, bearer) or _token_matches(configured, x_sift_token):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing token")


AuthDep = Depends(require_token)
