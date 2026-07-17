"""Ask — grounded natural-language Q&A over the snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from ..ai import query as ai_query
from ..ai.provider import LLMProvider
from ..ai.registry import ai_configured
from .deps import AuthDep, get_session_factory, get_settings
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
    settings = get_settings(request)
    with factory() as session:
        try:
            result = await ai_query.answer(session, provider, body.query)
        except Exception:  # noqa: BLE001 - a dead provider degrades, never 500s
            movies = ai_query.retrieve(session, body.query)
            return AskResponse(
                answer=(
                    "The AI provider didn't answer — check your connection in "
                    "Settings › Connections. The closest matches in your library "
                    "are listed below."
                ),
                provider="error",
                model=provider.model,
                latency_ms=0.0,
                ai_configured=ai_configured(settings),
                sources=[AskSource(tmdb_id=m.tmdb_id, title=m.title, year=m.year) for m in movies],
            )
    return AskResponse(
        answer=result.answer,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        ai_configured=ai_configured(settings),
        sources=[AskSource(tmdb_id=s.tmdb_id, title=s.title, year=s.year) for s in result.sources],
    )
