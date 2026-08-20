"""OpenAI Chat Completions provider.

Deliberately a near-copy of ``anthropic.py`` rather than a shared abstraction.
The two APIs differ in exactly three places — the auth header, the shape of the
message list, and where the text lives in the response — and a base class hiding
three differences behind four hooks is harder to read than two short files that
each say what they do.

One wrinkle is real and is handled rather than assumed away: OpenAI renamed the
output cap from ``max_tokens`` to ``max_completion_tokens``, newer models reject
the old name, and older ones predate the new one. Since the model here is typed
in by hand, a request is sent with the new name and retried once with the old one
when — and only when — the API says that parameter was the problem.
"""

from __future__ import annotations

import time

import httpx

from .provider import Completion

_API = "https://api.openai.com"

# The default is a cheap, current, general-purpose model. It is a starting point
# rather than a recommendation: the Test button lists what the key can actually
# reach, so a wrong guess here costs one click to fix.
DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self._max_tokens = max_tokens
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_API,
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            timeout=60.0,
            transport=transport,
        )

    def _body(self, system: str, prompt: str, cap_field: str) -> dict[str, object]:
        return {
            "model": self.model,
            cap_field: self._max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }

    async def complete(self, *, system: str, prompt: str) -> Completion:
        start = time.monotonic()
        resp = await self._client.post(
            "/v1/chat/completions", json=self._body(system, prompt, "max_completion_tokens")
        )
        if resp.status_code == 400 and "max_completion_tokens" in resp.text:
            # An older model that predates the rename. Retried once, and only on
            # the specific complaint — a blanket retry would double every genuine
            # failure, including a rate limit.
            resp = await self._client.post(
                "/v1/chat/completions", json=self._body(system, prompt, "max_tokens")
            )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        text = ""
        if choices and isinstance(choices[0], dict):
            text = str((choices[0].get("message") or {}).get("content") or "")
        latency = (time.monotonic() - start) * 1000
        return Completion(
            text=text.strip(), provider="openai", model=self.model, latency_ms=round(latency, 1)
        )

    async def health(self) -> bool:
        return bool(self._api_key)

    async def aclose(self) -> None:
        await self._client.aclose()


async def list_models(
    key: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    """Model ids the key can use — a free call that also proves the key works.

    Lives beside the provider so there is exactly one definition of how Sift talks
    to OpenAI. The list is filtered to chat-capable families and sorted, because
    a key can see well over a hundred ids — embeddings, audio, moderation, image
    models — and a dropdown of those is worse than no dropdown.
    """
    async with httpx.AsyncClient(
        base_url=_API,
        headers={"authorization": f"Bearer {key}"},
        timeout=8.0,
        transport=transport,
    ) as client:
        resp = await client.get("/v1/models")
        resp.raise_for_status()
    data = resp.json().get("data", [])
    ids = [m["id"] for m in data if isinstance(m, dict) and m.get("id")]
    chat = [
        mid
        for mid in ids
        if mid.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-"))
        and not any(x in mid for x in ("audio", "realtime", "transcribe", "tts", "image"))
    ]
    # If the filter matches nothing the key is still valid and the caller still
    # needs an answer, so fall back to everything rather than reporting none.
    return sorted(chat or ids)
