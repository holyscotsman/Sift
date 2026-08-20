"""Select providers from configuration, honoring the AI engine mode.

``ai.mode`` picks the engine: ``tandem`` (a local model drafts, a hosted one
refines), or ``anthropic`` / ``openai`` / ``ollama`` to pin every task to one.

**There is one hosted slot, not two.** Anthropic and OpenAI answer the same
question in the same shape, so keeping both live would double the cost to get two
opinions nothing here is equipped to choose between — and nothing in Sift decides
correctness from an AI answer in the first place. Under ``tandem``, Anthropic
takes the slot when it is keyed and OpenAI takes it otherwise; that order is
deliberate rather than incidental, so an instance that has always used Claude
keeps using it after an OpenAI key is added.

Hosted keys are read from the UI-entered config first, then from the bare
``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` env vars (no ``SIFT_`` prefix), which
is where hosts like Render expect them. With nothing configured, a deterministic
stub keeps every AI surface working — degraded, never erroring.
"""

from __future__ import annotations

import os

from ..config import Settings
from .anthropic import AnthropicProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .provider import LLMProvider, StubProvider

MODES = ("tandem", "anthropic", "openai", "ollama")

# Modes under which each hosted provider is allowed to be built.
_ANTHROPIC_MODES = ("tandem", "anthropic")
_OPENAI_MODES = ("tandem", "openai")
_LOCAL_MODES = ("tandem", "ollama")

HostedProvider = AnthropicProvider | OpenAIProvider


def anthropic_key(settings: Settings) -> str | None:
    """UI/wizard-entered key wins; otherwise the ANTHROPIC_API_KEY env var (Render)."""
    if settings.ai.anthropic_api_key is not None:
        return settings.ai.anthropic_api_key.get_secret_value() or None
    return os.environ.get("ANTHROPIC_API_KEY") or None


def openai_key(settings: Settings) -> str | None:
    """UI/wizard-entered key wins; otherwise the OPENAI_API_KEY env var (Render)."""
    if settings.ai.openai_api_key is not None:
        return settings.ai.openai_api_key.get_secret_value() or None
    return os.environ.get("OPENAI_API_KEY") or None


def _mode(settings: Settings) -> str:
    mode = (settings.ai.mode or "tandem").lower()
    return mode if mode in MODES else "tandem"


def hosted_choice(settings: Settings) -> str | None:
    """Which hosted provider the current mode and keys resolve to, if any.

    A pure function — it never constructs a provider, because each one opens an
    httpx client and the callers that only want to *know* far outnumber the ones
    that want to *use*.
    """
    mode = _mode(settings)
    if mode in _ANTHROPIC_MODES and anthropic_key(settings):
        return "anthropic"
    if mode in _OPENAI_MODES and openai_key(settings):
        return "openai"
    return None


def _build_hosted(settings: Settings) -> HostedProvider | None:
    choice = hosted_choice(settings)
    if choice == "anthropic":
        key = anthropic_key(settings)
        return AnthropicProvider(key, settings.ai.anthropic_model) if key else None
    if choice == "openai":
        key = openai_key(settings)
        return OpenAIProvider(key, settings.ai.openai_model) if key else None
    return None


def build_providers(
    settings: Settings,
) -> tuple[OllamaProvider | None, HostedProvider | None]:
    """(local, hosted) as the engine mode allows — either may be ``None``."""
    mode = _mode(settings)
    local: OllamaProvider | None = None
    if mode in _LOCAL_MODES and settings.ai.local_enabled:
        local = OllamaProvider(settings.ai.local_base_url, settings.ai.local_model)
    return local, _build_hosted(settings)


def ai_configured(settings: Settings) -> bool:
    """Is at least one real provider usable under the current mode?"""
    mode = _mode(settings)
    has_local = mode in _LOCAL_MODES and settings.ai.local_enabled
    return has_local or hosted_choice(settings) is not None


def compare_available(settings: Settings) -> bool:
    """Can Ask offer side-by-side answers? Needs a local model AND a hosted one
    under tandem. A pure check — never constructs providers (each opens an httpx
    client)."""
    return (
        _mode(settings) == "tandem"
        and settings.ai.local_enabled
        and hosted_choice(settings) is not None
    )


def build_llm_provider(settings: Settings) -> LLMProvider:
    """The single conversational provider (Ask): the hosted model when allowed and
    keyed, else the local model, else the deterministic stub. Constructs only the
    provider it returns — each provider opens an httpx client, so building several
    here would leak the discarded ones."""
    hosted = _build_hosted(settings)
    if hosted is not None:
        return hosted
    if _mode(settings) in _LOCAL_MODES and settings.ai.local_enabled:
        return OllamaProvider(settings.ai.local_base_url, settings.ai.local_model)
    return StubProvider()
