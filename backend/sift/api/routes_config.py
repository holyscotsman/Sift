"""In-app connection config: read (masked), save (rebuilds services), and test.

All routes are gated. ``test`` overlays the *provided* values on the base settings
and probes without saving, so the wizard can validate a key before committing it.
Saving deep-merges the patch, then rebuilds the live services so the change takes
effect immediately.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from ..services import config_store, runtime
from ..services.health import check_service
from .deps import AuthDep, get_session_factory, get_state
from .schemas import ConnectionsIn, ConnectionsOut, ConnectionTestIn, ServiceHealth

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[AuthDep])


@router.get("", response_model=ConnectionsOut)
def read_config(
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> ConnectionsOut:
    with factory() as session:
        cfg = config_store.get_config(session)
    return ConnectionsOut(connections=config_store.masked(cfg))


@router.put("", response_model=ConnectionsOut)
async def save_config(body: ConnectionsIn, request: Request) -> ConnectionsOut:
    state = get_state(request)
    with state.session_factory() as session:
        merged = config_store.set_config(session, body.connections)
    # Re-overlay + swap the live services (health, scan, posters, writer, LLM).
    await runtime.rebuild(state)
    return ConnectionsOut(connections=config_store.masked(merged))


@router.post("/test/{service}", response_model=ServiceHealth)
async def test_config(service: str, body: ConnectionTestIn, request: Request) -> ServiceHealth:
    state = get_state(request)
    # Probe the *unsaved* values by overlaying them on the base config.
    trial = config_store.apply_to_settings(state.base_settings, {service: body.values})

    if service in ("plex", "radarr", "tautulli", "tmdb"):
        status = await check_service(trial, service)
        return ServiceHealth(
            service=status.service, ok=status.ok, detail=status.detail, latency_ms=status.latency_ms
        )

    if service == "ollama":
        base = trial.ai.local_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
            models = resp.json().get("models", [])
            count = len(models) if isinstance(models, list) else 0
            return ServiceHealth(
                service="ollama", ok=True, detail=f"reachable ({count} model(s))", latency_ms=None
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, not raised
            return ServiceHealth(service="ollama", ok=False, detail=str(exc)[:120], latency_ms=None)

    if service == "anthropic":
        # A live call would cost tokens; treat a present key as configured. The real
        # provider swaps in on save and any auth error surfaces on first use.
        ok = trial.ai.anthropic_api_key is not None
        return ServiceHealth(
            service="anthropic",
            ok=ok,
            detail="key set" if ok else "no key",
            latency_ms=None,
        )

    raise HTTPException(status_code=404, detail=f"unknown service {service!r}")
