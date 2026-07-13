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


def anthropic_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    return key or None


def ai_configured() -> bool:
    return anthropic_key() is not None


def build_llm_provider(settings: Settings) -> LLMProvider:
    key = anthropic_key()
    if key:
        return AnthropicProvider(key, settings.ai.anthropic_model)
    return StubProvider()
