"""Select a provider from configuration / environment.

The Anthropic key is read from ``ANTHROPIC_API_KEY`` (no ``SIFT_`` prefix), which
is where hosts like Render expect it. With no key, the deterministic stub is used
so the app degrades gracefully rather than erroring.
"""

from __future__ import annotations

import os

from ..config import Settings
from .anthropic import AnthropicProvider
from .provider import LLMProvider, StubProvider


def anthropic_key(settings: Settings) -> str | None:
    """UI/wizard-entered key wins; otherwise the ANTHROPIC_API_KEY env var (Render)."""
    if settings.ai.anthropic_api_key is not None:
        return settings.ai.anthropic_api_key.get_secret_value() or None
    return os.environ.get("ANTHROPIC_API_KEY") or None


def ai_configured(settings: Settings) -> bool:
    return anthropic_key(settings) is not None


def build_llm_provider(settings: Settings) -> LLMProvider:
    key = anthropic_key(settings)
    if key:
        return AnthropicProvider(key, settings.ai.anthropic_model)
    return StubProvider()
