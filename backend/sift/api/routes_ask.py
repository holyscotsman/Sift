"""Ask — grounded natural-language Q&A over the snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from ..ai import query as ai_query
from ..ai.provider import LLMProvider
from ..ai.registry import ai_configured
from .deps import AuthDep, get_session_factory
from .schemas import AskRequest, AskResponse, AskSource

router = APIRouter(prefix="/api", tags=["ask"], dependencies=[AuthDep])


def _get_llm(request: Request) -> LLMProvider:
    return request.app.state.sift.llm  # type: ignore[no-any-return]


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> AskResponse:
    provider = _get_llm(request)
    with factory() as session:
        result = await ai_query.answer(session, provider, body.query)
    return AskResponse(
        answer=result.answer,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        ai_configured=ai_configured(),
        sources=[AskSource(tmdb_id=s.tmdb_id, title=s.title, year=s.year) for s in result.sources],
    )
