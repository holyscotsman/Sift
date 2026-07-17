"""LLM provider interface + a deterministic stub used for tests and for graceful
degradation when no provider is configured."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: float
    cost_usd: float | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, *, system: str, prompt: str) -> Completion: ...
    async def health(self) -> bool: ...
    async def aclose(self) -> None: ...


class StubProvider:
    """Deterministic no-network provider. When no real provider is configured the
    Ask flow still works — retrieval is deterministic; the stub just phrases it."""

    name = "stub"

    def __init__(self, model: str = "none") -> None:
        self.model = model

    async def complete(self, *, system: str, prompt: str) -> Completion:
        text = (
            "AI answers aren't configured yet — connect Anthropic or a local Ollama in "
            "Settings › Connections to enable them. In the meantime, the titles below "
            "are the closest matches in your library for that question."
        )
        return Completion(text=text, provider="stub", model=self.model, latency_ms=0.0)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None
