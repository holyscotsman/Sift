"""Shared FastAPI dependencies: app state accessors and API-token gating."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from ..actions.engine import ActionEngine
from ..ai.provider import LLMProvider
from ..config import Settings
from ..services.posters import PosterCache
from ..services.scanner import ProgressHub


@dataclass
class AppState:
    settings: Settings
    session_factory: sessionmaker[Session]
    engine: ActionEngine
    hub: ProgressHub
    llm: LLMProvider
    posters: PosterCache


def get_state(request: Request) -> AppState:
    return request.app.state.sift  # type: ignore[no-any-return]


def get_settings(request: Request) -> Settings:
    return get_state(request).settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return get_state(request).session_factory


def get_action_engine(request: Request) -> ActionEngine:
    return get_state(request).engine


def presented_token(authorization: str | None, x_sift_token: str | None) -> str | None:
    """Pull the token from an Authorization: Bearer header or X-Sift-Token."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return x_sift_token


def token_accepted(state: AppState, presented: str | None) -> bool:
    """Central auth decision, shared by the API gate and the poster route.

    Accepts (a) the static ``SIFT_SERVER__API_TOKEN`` when configured, or (b) a valid
    username/password session token once an account exists. Before any account or
    static token is set up, the API is open so the setup wizard is reachable.
    """
    from ..services import auth  # local import avoids a cycle at module load

    static = state.settings.server.api_token
    static_secret = static.get_secret_value() if static else None
    if static_secret and presented == static_secret:
        return True
    with state.session_factory() as session:
        account_configured = auth.is_configured(session)
        if account_configured and presented and auth.token_valid(session, presented):
            return True
    # Nothing configured yet → open (fresh install, local dev). Once either the static
    # token or an account exists, a valid credential is required.
    return not static_secret and not account_configured


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_sift_token: str | None = Header(default=None),
) -> None:
    """Gate every ``/api/*`` call once auth (static token or an account) is set up."""
    presented = presented_token(authorization, x_sift_token)
    if token_accepted(get_state(request), presented):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")


AuthDep = Depends(require_token)
