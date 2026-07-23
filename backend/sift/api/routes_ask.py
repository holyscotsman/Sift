"""Ask — grounded natural-language Q&A over the snapshot.

``mode="compare"`` asks BOTH providers (tandem only) to phrase the same
deterministic retrieval, side by side. Retrieval stays deterministic and the
authored data stays authoritative — compare changes phrasing surface, nothing
else. The second provider failing degrades to a single answer, never a 500.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from ..ai import query as ai_query
from ..ai.ollama import OllamaProvider
from ..ai.provider import LLMProvider
from ..ai.registry import ai_configured, compare_available
from ..config import Settings
from .deps import AuthDep, get_session_factory, get_settings
from .schemas import AskAlternate, AskRequest, AskResponse, AskSource

log = logging.getLogger("sift.ask")

router = APIRouter(prefix="/api", tags=["ask"], dependencies=[AuthDep])


def _get_llm(request: Request) -> LLMProvider:
    return request.app.state.sift.llm  # type: ignore[no-any-return]


def _build_alternate(settings: Settings) -> LLMProvider | None:
    """The second voice for compare mode. Under tandem the primary is Anthropic,
    so the alternate is always the local model. Constructed per-request and
    closed after use (providers own an httpx client)."""
    if not compare_available(settings):
        return None
    return OllamaProvider(settings.ai.local_base_url, settings.ai.local_model)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> AskResponse:
    provider = _get_llm(request)
    settings = get_settings(request)
    alternate_provider = _build_alternate(settings) if body.mode == "compare" else None
    with factory() as session:
        movies = ai_query.retrieve(session, body.query)
    sources = [AskSource(tmdb_id=m.tmdb_id, title=m.title, year=m.year) for m in movies]

    alternate: AskAlternate | None = None
    try:
        if alternate_provider is not None:
            # One retrieval, two phrasings, concurrently. The alternate failing
            # must never sink the primary answer.
            primary_res, alt_res = await asyncio.gather(
                ai_query.answer_with(provider, movies, body.query),
                ai_query.answer_with(alternate_provider, movies, body.query),
                return_exceptions=True,
            )
            if not isinstance(alt_res, BaseException):
                alternate = AskAlternate(
                    answer=alt_res.answer,
                    provider=alt_res.provider,
                    model=alt_res.model,
                    latency_ms=alt_res.latency_ms,
                )
            else:
                log.info("compare alternate failed: %s", alt_res)
            if isinstance(primary_res, BaseException):
                raise primary_res
            result = primary_res
        else:
            result = await ai_query.answer_with(provider, movies, body.query)
    except Exception:  # noqa: BLE001 - a dead provider degrades, never 500s
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
            sources=sources,
            alternate=alternate,
        )
    finally:
        if alternate_provider is not None:
            try:
                await alternate_provider.aclose()
            except Exception as exc:  # noqa: BLE001 - best-effort close
                log.debug("alternate aclose failed: %s", exc)

    return AskResponse(
        answer=result.answer,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        ai_configured=ai_configured(settings),
        sources=sources,
        alternate=alternate,
    )
