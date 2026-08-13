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

from ..ai import anthropic as anthropic_ai
from ..ai.registry import anthropic_key
from ..ingest import sections as section_plan
from ..services import config_store, reset, runtime
from ..services.health import check_service
from .deps import AuthDep, get_session_factory, get_state
from .schemas import (
    ActionsConfigIn,
    ActionsConfigOut,
    ConnectionsIn,
    ConnectionsOut,
    ConnectionTestIn,
    ResetRequest,
    ResetResponse,
    SectionKindsIn,
    SectionPlanOut,
    SectionsResponse,
    ServiceHealth,
)

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


@router.get("/actions", response_model=ActionsConfigOut)
def read_actions(request: Request) -> ActionsConfigOut:
    return ActionsConfigOut(dry_run=get_state(request).settings.actions.dry_run)


@router.put("/actions", response_model=ActionsConfigOut)
async def save_actions(body: ActionsConfigIn, request: Request) -> ActionsConfigOut:
    state = get_state(request)
    with state.session_factory() as session:
        config_store.set_actions(session, body.dry_run)
    await runtime.rebuild(state)
    return ActionsConfigOut(dry_run=state.settings.actions.dry_run)


@router.post("/reset", response_model=ResetResponse)
async def reset_instance(body: ResetRequest, request: Request) -> ResetResponse:
    """Factory reset back to the setup wizard. Optionally keeps the thumbnail cache."""
    state = get_state(request)
    reset.wipe_data(state.session_factory)
    cleared = 0 if body.keep_thumbnails else state.posters.clear()
    # Config + account are gone now; re-overlay so live services return to the base.
    await runtime.rebuild(state)
    return ResetResponse(ok=True, cleared_posters=cleared)


@router.post("/test/{service}", response_model=ServiceHealth)
async def test_config(service: str, body: ConnectionTestIn, request: Request) -> ServiceHealth:
    state = get_state(request)
    # Probe the *unsaved* values by overlaying them on the base config.
    trial = config_store.apply_to_settings(state.base_settings, {service: body.values})

    if service in ("plex", "radarr", "sonarr", "overseerr", "tautulli", "tmdb"):
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
            low = base.lower()
            if "localhost" in low or "127.0.0.1" in low:
                # The probe runs on the Sift server, so "localhost" is the server, not
                # the user's machine — the #1 cause of this failing on a hosted deploy.
                detail = (
                    "unreachable — 'localhost' is the Sift server, not your machine. "
                    "Expose Ollama at a public URL (tunnel or port-forward) instead."
                )
            elif low.startswith("https://"):
                detail = "unreachable — try http:// (Ollama serves plain HTTP by default)."
            else:
                detail = str(exc)[:120]
            return ServiceHealth(service="ollama", ok=False, detail=detail, latency_ms=None)

    if service == "anthropic":
        key = anthropic_key(trial)
        if not key:
            return ServiceHealth(service="anthropic", ok=False, detail="no key", latency_ms=None)
        try:
            models = await anthropic_ai.list_models(key)
        except httpx.HTTPStatusError as exc:
            detail = (
                "key rejected (401) — check it and try again."
                if exc.response.status_code == 401
                else f"Anthropic returned HTTP {exc.response.status_code}."
            )
            return ServiceHealth(service="anthropic", ok=False, detail=detail, latency_ms=None)
        except Exception:  # noqa: BLE001 - a raw exception could echo request details
            return ServiceHealth(
                service="anthropic",
                ok=False,
                detail="couldn't reach Anthropic — network problem on the Sift server.",
                latency_ms=None,
            )
        return ServiceHealth(
            service="anthropic",
            ok=True,
            detail=f"key verified ({len(models)} model(s) available)",
            latency_ms=None,
            models=models,
        )

    raise HTTPException(status_code=404, detail=f"unknown service {service!r}")


@router.get("/sections", response_model=SectionsResponse)
async def list_sections(request: Request) -> SectionsResponse:
    """Every Plex library, and what Sift will do with each.

    Worth looking at once. Plex calls a Home Videos library a *movie* library, so
    without an override family footage is read as films — into the removal queue,
    the film counts, and the size baselines every verdict is measured against.
    Sift leaves those alone by default because they carry no metadata agent, but
    the decision is shown rather than assumed.
    """
    from ..clients.plex import PlexClient

    state = get_state(request)
    settings = state.settings
    if not settings.plex.enabled or not settings.plex.base_url:
        return SectionsResponse(sections=[], detail="Plex isn't connected yet.")
    try:
        client = PlexClient(settings.plex)
    except Exception as exc:  # noqa: BLE001 - a config problem, not a crash
        return SectionsResponse(sections=[], detail=str(exc))
    try:
        raw = await client.get_sections()
    except Exception:  # noqa: BLE001 - unreachable Plex is a status, not a 500
        return SectionsResponse(sections=[], detail="Couldn't reach Plex to list libraries.")
    finally:
        await client.aclose()

    plans = section_plan.plan(raw, settings.plex.section_kinds)
    return SectionsResponse(
        sections=[
            SectionPlanOut(
                key=p.key,
                title=p.title,
                plex_type=p.plex_type,
                agent=p.agent,
                kind=p.kind,
                reason=p.reason,
                overridden=p.overridden,
            )
            for p in plans
        ]
    )


@router.put("/sections", response_model=SectionsResponse)
async def set_sections(
    body: SectionKindsIn,
    request: Request,
    factory: sessionmaker[Session] = Depends(get_session_factory),
) -> SectionsResponse:
    """Correct the mapping. Takes effect on the next scan."""
    with factory() as session:
        config_store.set_config(session, {"plex": {"section_kinds": body.section_kinds}})
    # Rebuild the live settings, or the next scan reads the old mapping.
    await runtime.rebuild(request.app)
    return await list_sections(request)
