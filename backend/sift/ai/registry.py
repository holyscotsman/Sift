"""Select providers from configuration, honoring the AI engine mode.

``ai.mode`` picks the engine: ``tandem`` (both, when configured — local drafts,
Anthropic refines), ``anthropic`` (Claude only), or ``ollama`` (local only). The
Anthropic key is read from the UI-entered config first, then ``ANTHROPIC_API_KEY``
(no ``SIFT_`` prefix), which is where hosts like Render expect it. With nothing
configured, a deterministic stub keeps every AI surface working — degraded, never
erroring.
"""

from __future__ import annotations

import os

from ..config import Settings
from .anthropic import AnthropicProvider
from .ollama import OllamaProvider
from .provider import LLMProvider, StubProvider

MODES = ("tandem", "anthropic", "ollama")


def anthropic_key(settings: Settings) -> str | None:
    """UI/wizard-entered key wins; otherwise the ANTHROPIC_API_KEY env var (Render)."""
    if settings.ai.anthropic_api_key is not None:
        return settings.ai.anthropic_api_key.get_secret_value() or None
    return os.environ.get("ANTHROPIC_API_KEY") or None


def _mode(settings: Settings) -> str:
    mode = (settings.ai.mode or "tandem").lower()
    return mode if mode in MODES else "tandem"


def build_providers(
    settings: Settings,
) -> tuple[OllamaProvider | None, AnthropicProvider | None]:
    """(local, anthropic) as the engine mode allows — either may be ``None``."""
    mode = _mode(settings)
    local: OllamaProvider | None = None
    remote: AnthropicProvider | None = None
    if mode in ("tandem", "ollama") and settings.ai.local_enabled:
        local = OllamaProvider(settings.ai.local_base_url, settings.ai.local_model)
    if mode in ("tandem", "anthropic"):
        key = anthropic_key(settings)
        if key:
            remote = AnthropicProvider(key, settings.ai.anthropic_model)
    return local, remote


def ai_configured(settings: Settings) -> bool:
    """Is at least one real provider usable under the current mode?"""
    mode = _mode(settings)
    has_local = mode in ("tandem", "ollama") and settings.ai.local_enabled
    has_remote = mode in ("tandem", "anthropic") and anthropic_key(settings) is not None
    return has_local or has_remote


def compare_available(settings: Settings) -> bool:
    """Can Ask offer side-by-side answers? Needs BOTH providers under tandem.
    A pure check — never constructs providers (each opens an httpx client)."""
    mode = _mode(settings)
    return mode == "tandem" and settings.ai.local_enabled and anthropic_key(settings) is not None


def build_llm_provider(settings: Settings) -> LLMProvider:
    """The single conversational provider (Ask): Anthropic when allowed and keyed,
    else the local model, else the deterministic stub. Constructs only the provider
    it returns — each provider opens an httpx client, so building the pair here
    would leak the discarded one."""
    mode = _mode(settings)
    if mode in ("tandem", "anthropic"):
        key = anthropic_key(settings)
        if key:
            return AnthropicProvider(key, settings.ai.anthropic_model)
    if mode in ("tandem", "ollama") and settings.ai.local_enabled:
        return OllamaProvider(settings.ai.local_base_url, settings.ai.local_model)
    return StubProvider()
