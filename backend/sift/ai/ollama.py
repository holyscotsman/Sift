"""Local Ollama provider (implements the same LLMProvider interface).

Used as the cheap bulk pass in AI review; the hard-reasoning pass routes to
Anthropic. Talks to Ollama's ``/api/generate`` (non-streaming). Never used to decide
correctness — it only drafts advisory notes.
"""

from __future__ import annotations

import time

import httpx

from .provider import Completion


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    async def complete(self, *, system: str, prompt: str) -> Completion:
        start = time.monotonic()
        resp = await self._client.post(
            "/api/generate",
            json={"model": self.model, "system": system, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("response", "")).strip()
        latency = round((time.monotonic() - start) * 1000, 1)
        return Completion(text=text, provider="ollama", model=self.model, latency_ms=latency)

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code < 400
        except Exception:  # noqa: BLE001 - health is a boolean probe
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
