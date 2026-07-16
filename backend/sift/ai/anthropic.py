"""Anthropic Messages API provider."""

from __future__ import annotations

import time

import httpx

from .provider import Completion

_API = "https://api.anthropic.com"
_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._max_tokens = max_tokens
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_API,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _VERSION,
                "content-type": "application/json",
            },
            timeout=60.0,
            transport=transport,
        )

    async def complete(self, *, system: str, prompt: str) -> Completion:
        start = time.monotonic()
        resp = await self._client.post(
            "/v1/messages",
            json={
                "model": self.model,
                "max_tokens": self._max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        latency = (time.monotonic() - start) * 1000
        return Completion(
            text=text.strip(), provider="anthropic", model=self.model, latency_ms=round(latency, 1)
        )

    async def health(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()
