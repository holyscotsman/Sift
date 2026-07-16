"""Rebuild the live app services after connection config changes.

The scan pipeline, health checks, poster cache, Radarr writer, and LLM provider are
all built from the effective settings. When the user saves new connections in the
wizard/Settings we re-overlay the base config and swap the affected services in
place, so the change takes effect without a restart.
"""

from __future__ import annotations

import logging

from ..actions.engine import ActionEngine
from ..actions.radarr_writes import RadarrWriter
from ..ai.registry import build_llm_provider
from ..api.deps import AppState
from . import config_store
from .posters import PosterCache

log = logging.getLogger("sift.runtime")


async def rebuild(state: AppState) -> None:
    with state.session_factory() as session:
        conn = config_store.get_config(session)
        actions_cfg = config_store.get_actions(session)
    effective = config_store.apply_to_settings(state.base_settings, conn, actions_cfg)
    state.settings = effective
    state.posters = PosterCache(effective, state.session_factory)
    state.engine = ActionEngine(
        state.session_factory, RadarrWriter(effective.radarr), audit=state.engine.audit
    )
    old_llm = state.llm
    state.llm = build_llm_provider(effective)
    if old_llm is not state.llm:
        try:
            await old_llm.aclose()
        except Exception as exc:  # noqa: BLE001 - closing the old client is best-effort
            log.debug("old llm aclose failed: %s", exc)
