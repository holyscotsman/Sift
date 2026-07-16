"""UI-entered connection config, persisted in the ``settings`` table.

Keys entered in the setup wizard / Settings are stored here (key ``connections``)
and **overlaid on top of** the env/toml base, so a hosted instance can be configured
entirely from the browser without touching Render. Secrets are held in the local
SQLite in plaintext — acceptable for a single-user self-hosted app that's gated
behind login; on a free host the DB (and thus this config) resets on redeploy unless
a persistent disk is attached.

Only known fields per service are accepted; everything else is ignored.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr
from sqlalchemy.orm import Session

from ..config import Settings
from ..db.models import Setting

_CONN_KEY = "connections"
_ACTIONS_KEY = "actions"

# Non-secret fields we echo back; secret fields become ``<name>_set`` booleans.
_SECRET_FIELDS = {"token", "api_key"}
_ALLOWED: dict[str, set[str]] = {
    "plex": {"base_url", "token", "kids_sections"},
    "radarr": {"base_url", "api_key"},
    "tautulli": {"base_url", "api_key", "kids_accounts"},
    "tmdb": {"api_key", "language"},
    "ollama": {"base_url", "model"},
    "anthropic": {"api_key", "model"},
}


def get_config(session: Session) -> dict[str, Any]:
    row = session.get(Setting, _CONN_KEY)
    return dict(row.value) if row and row.value else {}


def set_config(session: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a per-service patch. ``None`` values are skipped (leave unchanged);
    an empty string clears a field. Returns the merged config."""
    current = get_config(session)
    for service, fields in patch.items():
        if service not in _ALLOWED or not isinstance(fields, dict):
            continue
        merged = dict(current.get(service, {}))
        for key, value in fields.items():
            if key not in _ALLOWED[service] or value is None:
                continue
            merged[key] = value
        current[service] = merged
    session.merge(Setting(key=_CONN_KEY, value=current))
    session.commit()
    return current


def get_actions(session: Session) -> dict[str, Any]:
    row = session.get(Setting, _ACTIONS_KEY)
    return dict(row.value) if row and row.value else {}


def set_actions(session: Session, dry_run: bool) -> None:
    session.merge(Setting(key=_ACTIONS_KEY, value={"dry_run": bool(dry_run)}))
    session.commit()


def masked(config: dict[str, Any]) -> dict[str, Any]:
    """Config safe to send to the client: secrets replaced with ``<field>_set`` flags."""
    out: dict[str, Any] = {}
    for service, fields in config.items():
        safe: dict[str, Any] = {}
        for key, value in (fields or {}).items():
            if key in _SECRET_FIELDS:
                safe[f"{key}_set"] = bool(value)
            else:
                safe[key] = value
        out[service] = safe
    return out


def _s(value: Any) -> str | None:
    text = (value or "").strip() if isinstance(value, str) else value
    return text or None


def apply_to_settings(
    base: Settings, config: dict[str, Any], actions: dict[str, Any] | None = None
) -> Settings:
    """Return a copy of ``base`` with the stored connection config overlaid.

    ``model_copy`` (not re-constructing ``Settings``) is deliberate — re-instantiating
    a ``BaseSettings`` would re-read env/.env/toml and clobber the overlay.
    """
    eff = base.model_copy(deep=True)

    if actions and "dry_run" in actions:
        eff.actions.dry_run = bool(actions["dry_run"])

    plex = config.get("plex") or {}
    if _s(plex.get("base_url")):
        eff.plex.base_url = _s(plex["base_url"])
    if _s(plex.get("token")):
        eff.plex.token = SecretStr(plex["token"])
        eff.plex.enabled = True
    if isinstance(plex.get("kids_sections"), list):
        eff.plex.kids_sections = list(plex["kids_sections"])

    radarr = config.get("radarr") or {}
    if _s(radarr.get("base_url")):
        eff.radarr.base_url = _s(radarr["base_url"])
    if _s(radarr.get("api_key")):
        eff.radarr.api_key = SecretStr(radarr["api_key"])
        eff.radarr.enabled = True

    tautulli = config.get("tautulli") or {}
    if _s(tautulli.get("base_url")):
        eff.tautulli.base_url = _s(tautulli["base_url"])
    if _s(tautulli.get("api_key")):
        eff.tautulli.api_key = SecretStr(tautulli["api_key"])
        eff.tautulli.enabled = True
    if isinstance(tautulli.get("kids_accounts"), list):
        eff.tautulli.kids_accounts = list(tautulli["kids_accounts"])

    tmdb = config.get("tmdb") or {}
    if _s(tmdb.get("api_key")):
        eff.tmdb.api_key = SecretStr(tmdb["api_key"])
        eff.tmdb.enabled = True
    if _s(tmdb.get("language")):
        eff.tmdb.language = tmdb["language"]

    anthropic = config.get("anthropic") or {}
    if _s(anthropic.get("api_key")):
        eff.ai.anthropic_api_key = SecretStr(anthropic["api_key"])
    if _s(anthropic.get("model")):
        eff.ai.anthropic_model = anthropic["model"]

    ollama = config.get("ollama") or {}
    if _s(ollama.get("base_url")):
        eff.ai.local_base_url = _s(ollama["base_url"]) or eff.ai.local_base_url
        eff.ai.local_enabled = True
    if _s(ollama.get("model")):
        eff.ai.local_model = ollama["model"]

    return eff
