"""Restart and update, from inside the app.

Both of these hand control to the host rather than doing anything clever
themselves, because a web app cannot reliably restart or upgrade itself:

**Restart** asks the process to exit. On a managed host (Render, Fly, Railway,
any container platform with a restart policy) the supervisor brings it straight
back — that *is* the restart. Run Sift by hand, though, and nothing is watching,
so exiting just stops it. The response says which case you're in rather than
pretending they're the same, and the UI repeats the warning before you confirm.

**Update** pokes a deploy hook — a secret URL the host gives you that triggers a
build of the latest code. Sift never pulls or executes anything itself; the host
does the deploy exactly as it would for a push. With no hook configured this
returns a 400 explaining where to find one, instead of silently doing nothing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from ..services import config_store
from .deps import AuthDep, get_session_factory
from .schemas import RestartResponse, UpdateResponse

log = logging.getLogger("sift.system")

router = APIRouter(prefix="/api/system", tags=["system"], dependencies=[AuthDep])

# Long enough for the HTTP response to flush before the process goes away —
# otherwise the browser sees a dropped connection instead of the confirmation.
_EXIT_DELAY_SECONDS = 0.75


def _supervised() -> bool:
    """Is something going to restart us? Managed hosts set a marker variable; a
    bare local run sets none of them, and exiting there just stops the app."""
    return any(
        os.environ.get(var)
        for var in ("RENDER", "FLY_APP_NAME", "RAILWAY_ENVIRONMENT", "KOYEB_APP_NAME")
    )


def _terminate() -> None:
    # SIGTERM rather than os._exit: uvicorn runs its shutdown handlers, so the
    # database session and any in-flight scan close cleanly.
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/restart", response_model=RestartResponse)
async def restart() -> RestartResponse:
    """Stop the process. A managed host restarts it; a local run does not."""
    supervised = _supervised()
    loop = asyncio.get_running_loop()
    loop.call_later(_EXIT_DELAY_SECONDS, _terminate)
    log.warning("restart requested via the API (supervised=%s)", supervised)
    return RestartResponse(
        ok=True,
        supervised=supervised,
        detail=(
            "Restarting — the host will bring Sift back in a few seconds."
            if supervised
            else "Stopping. Nothing is supervising this process, so you'll need to "
            "start it again yourself."
        ),
    )


@router.post("/update", response_model=UpdateResponse)
async def update(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> UpdateResponse:
    """Trigger a redeploy of the latest code via the host's deploy hook."""
    with factory() as session:
        hook = (config_store.get_config(session).get("deploy") or {}).get("hook_url")
    if not hook:
        raise HTTPException(
            status_code=400,
            detail=(
                "No deploy hook set. In Render: your service → Settings → Deploy Hook, "
                "copy the URL, and paste it into Settings › Connections › Updates."
            ),
        )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(str(hook))
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - a bad hook is a config problem, not a crash
        raise HTTPException(
            status_code=400,
            detail="The deploy hook didn't accept the request — check the URL in Settings.",
        ) from exc
    log.info("update requested via the API; deploy hook accepted")
    return UpdateResponse(
        ok=True,
        detail=(
            "Update started. The host is building the latest code; "
            "Sift restarts when it's ready."
        ),
    )
