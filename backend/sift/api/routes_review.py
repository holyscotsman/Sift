"""AI review — advisory second opinion on the removal queue.

Runs the Ollama↔Anthropic orchestration over the current junk candidates and stores
a note on each. Advisory only: it never changes the deterministic keep/remove call.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..ai import review as ai_review
from .deps import AuthDep, get_state
from .schemas import ReviewRunResponse

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[AuthDep])


@router.post("/run", response_model=ReviewRunResponse)
async def run_review(
    request: Request, limit: int = Query(default=50, ge=1, le=500)
) -> ReviewRunResponse:
    state = get_state(request)
    result = await ai_review.run_review(state.session_factory, state.settings, limit=limit)
    return ReviewRunResponse(reviewed=result["reviewed"], provider=result["provider"])
