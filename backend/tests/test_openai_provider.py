"""OpenAI as a provider, and the single hosted slot it shares with Anthropic.

Two things are being pinned. The provider itself — can it talk to the API, and
does it survive OpenAI's rename of the output-cap parameter. And the selection
rule — which provider a given mode and set of keys resolves to, which is the part
that decides where the money goes and is invisible until a bill arrives.

There is deliberately one hosted slot rather than two. Both providers answer the
same question in the same shape, so running both would double the cost for two
opinions nothing here is equipped to choose between.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from sift.ai import openai as openai_ai
from sift.ai.anthropic import AnthropicProvider
from sift.ai.ollama import OllamaProvider
from sift.ai.openai import OpenAIProvider
from sift.ai.provider import StubProvider
from sift.ai.registry import (
    ai_configured,
    build_llm_provider,
    build_providers,
    compare_available,
    hosted_choice,
)

from .conftest import mock_transport


@pytest.fixture(autouse=True)
def no_ambient_keys(monkeypatch):
    """The env-var fallback is real and would otherwise leak a developer's own key
    into every assertion about "no key configured"."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ------------------------------------------------------------------- the provider


def _chat_handler(recorder: list[httpx.Request], *, reject_new_cap: bool = False):
    def handle(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        body = request.content.decode()
        if reject_new_cap and "max_completion_tokens" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: 'max_completion_tokens'"}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": " Seven Samurai "}}]},
        )

    return handle


async def test_it_reads_the_answer_out_of_a_chat_completion():
    seen: list[httpx.Request] = []
    provider = OpenAIProvider("k", "gpt-4o-mini", transport=mock_transport(_chat_handler(seen)))
    try:
        out = await provider.complete(system="You are a curator.", prompt="Name one film.")
    finally:
        await provider.aclose()

    assert out.text == "Seven Samurai"
    assert out.provider == "openai" and out.model == "gpt-4o-mini"
    assert seen[0].headers["authorization"] == "Bearer k"


async def test_it_retries_once_when_the_model_predates_the_parameter_rename():
    """OpenAI renamed the output cap. Newer models reject the old name, older ones
    predate the new one, and the model here is typed in by hand — so a request
    that fails on exactly that complaint is retried with the old spelling."""
    seen: list[httpx.Request] = []
    provider = OpenAIProvider(
        "k", "gpt-3.5-turbo", transport=mock_transport(_chat_handler(seen, reject_new_cap=True))
    )
    try:
        out = await provider.complete(system="s", prompt="p")
    finally:
        await provider.aclose()

    assert out.text == "Seven Samurai"
    assert len(seen) == 2
    assert "max_completion_tokens" in seen[0].content.decode()
    assert "max_tokens" in seen[1].content.decode()


async def test_NEGATIVE_CONTROL_an_ordinary_failure_is_not_retried():
    """NEGATIVE CONTROL: a blanket retry would double every genuine failure,
    including a rate limit — which is the worst possible moment to send a second
    request. Only the parameter complaint is retried."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limit exceeded"}})

    provider = OpenAIProvider("k", "gpt-4o-mini", transport=mock_transport(handle))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete(system="s", prompt="p")
    finally:
        await provider.aclose()

    assert len(seen) == 1


async def test_listing_models_keeps_the_chat_ones_and_drops_the_rest():
    """A key can see well over a hundred ids — embeddings, audio, moderation,
    images. A dropdown of those is worse than no dropdown."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o-mini"},
                    {"id": "gpt-4o"},
                    {"id": "o3-mini"},
                    {"id": "text-embedding-3-small"},
                    {"id": "gpt-4o-audio-preview"},
                    {"id": "dall-e-3"},
                    {"id": "whisper-1"},
                ]
            },
        )

    models = await openai_ai.list_models("k", transport=mock_transport(handle))
    assert models == ["gpt-4o", "gpt-4o-mini", "o3-mini"]


async def test_NEGATIVE_CONTROL_a_key_that_sees_no_chat_models_still_gets_an_answer():
    """NEGATIVE CONTROL: the filter is a convenience, not a gate. A key whose list
    matches nothing is still a valid key, and reporting "0 models" would read as
    "your key is broken"."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "some-future-model"}]})

    assert await openai_ai.list_models("k", transport=mock_transport(handle)) == [
        "some-future-model"
    ]


# ------------------------------------------------------------- the hosted slot


def _with(settings, *, anthropic=None, openai=None, local=False, mode="tandem"):
    settings.ai.mode = mode
    settings.ai.local_enabled = local
    settings.ai.anthropic_api_key = SecretStr(anthropic) if anthropic else None
    settings.ai.openai_api_key = SecretStr(openai) if openai else None
    return settings


def test_openai_takes_the_hosted_slot_when_it_is_the_only_key(settings):
    _with(settings, openai="sk-test")
    assert hosted_choice(settings) == "openai"
    assert ai_configured(settings) is True


def test_anthropic_keeps_the_slot_when_both_are_keyed(settings):
    """Deliberate, not incidental: an instance that has always used Claude keeps
    using it after an OpenAI key is added. The alternative is a silent switch of
    which account gets billed."""
    _with(settings, anthropic="sk-ant", openai="sk-oai")
    assert hosted_choice(settings) == "anthropic"


def test_pinning_the_mode_overrides_which_key_is_present(settings):
    """`openai` mode means OpenAI even with an Anthropic key sitting right there,
    which is the whole point of having a mode at all."""
    _with(settings, anthropic="sk-ant", openai="sk-oai", mode="openai")
    assert hosted_choice(settings) == "openai"

    _with(settings, anthropic="sk-ant", openai="sk-oai", mode="anthropic")
    assert hosted_choice(settings) == "anthropic"


def test_NEGATIVE_CONTROL_a_pinned_mode_with_no_matching_key_falls_to_nothing(settings):
    """NEGATIVE CONTROL: pinning to OpenAI with only an Anthropic key must not
    quietly use Anthropic. A mode that can be overruled by a key is not a mode."""
    _with(settings, anthropic="sk-ant", mode="openai")
    assert hosted_choice(settings) is None
    assert ai_configured(settings) is False


def test_openai_mode_never_builds_the_local_model(settings):
    """Each provider opens an httpx client, so building one that is never used
    leaks it. The pair returned has to match the mode exactly."""
    _with(settings, openai="sk-oai", local=True, mode="openai")
    local, hosted = build_providers(settings)
    assert local is None
    assert isinstance(hosted, OpenAIProvider)


def test_tandem_pairs_the_local_model_with_whichever_hosted_one_is_keyed(settings):
    _with(settings, openai="sk-oai", local=True, mode="tandem")
    local, hosted = build_providers(settings)
    assert isinstance(local, OllamaProvider)
    assert isinstance(hosted, OpenAIProvider)
    assert compare_available(settings) is True

    _with(settings, anthropic="sk-ant", local=True, mode="tandem")
    _local, hosted = build_providers(settings)
    assert isinstance(hosted, AnthropicProvider)


def test_ask_uses_openai_when_that_is_what_is_configured(settings):
    _with(settings, openai="sk-oai")
    assert isinstance(build_llm_provider(settings), OpenAIProvider)


def test_NEGATIVE_CONTROL_nothing_configured_still_answers(settings):
    """NEGATIVE CONTROL: every AI surface degrades rather than erroring. A stub
    that phrased itself as a failure would make an optional feature look broken."""
    _with(settings)
    assert isinstance(build_llm_provider(settings), StubProvider)
    assert ai_configured(settings) is False
    assert compare_available(settings) is False


def test_the_env_var_fallback_works_for_openai_too(settings, monkeypatch):
    """Render and friends set a bare OPENAI_API_KEY. Supporting it for one
    provider and not the other is the kind of asymmetry nobody discovers until
    they have typed the key into the UI as well."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    _with(settings)
    assert hosted_choice(settings) == "openai"


# ------------------------------------------------------------------ the endpoints


@pytest.fixture
def client(settings, factory):
    from fastapi.testclient import TestClient

    from sift.main import create_app

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_an_openai_key_saves_and_comes_back_masked(client):
    """The whole point of the database and the login: a key entered once is stored
    and not asked for again. It must never come back in plaintext, and the UI
    still has to know that one is set."""
    c, _ = client
    c.put(
        "/api/config",
        json={"connections": {"openai": {"api_key": "sk-secret", "model": "gpt-4o"}}},
    )

    body = c.get("/api/config").json()["connections"]
    assert body["openai"]["api_key_set"] is True
    assert "sk-secret" not in str(body)
    assert body["openai"]["model"] == "gpt-4o"


def test_NEGATIVE_CONTROL_an_unregistered_service_is_not_stored(client):
    """NEGATIVE CONTROL: `_ALLOWED` is a whitelist, and a test that only ever
    saves registered services would pass with the whitelist deleted."""
    c, _ = client
    c.put("/api/config", json={"connections": {"nonsense": {"api_key": "x"}}})
    assert "nonsense" not in c.get("/api/config").json()["connections"]


def test_testing_an_openai_key_reports_the_models_it_can_reach(client, monkeypatch):
    c, _ = client

    async def fake_list(key, *, transport=None):
        assert key == "sk-test"
        return ["gpt-4o", "gpt-4o-mini"]

    monkeypatch.setattr(openai_ai, "list_models", fake_list)
    body = c.post("/api/config/test/openai", json={"values": {"api_key": "sk-test"}}).json()

    assert body["ok"] is True and body["models"] == ["gpt-4o", "gpt-4o-mini"]


def test_a_rejected_openai_key_says_so_in_words_someone_can_act_on(client, monkeypatch):
    c, _ = client

    async def fake_list(key, *, transport=None):
        raise httpx.HTTPStatusError(
            "401",
            request=httpx.Request("GET", "https://api.openai.com/v1/models"),
            response=httpx.Response(401),
        )

    monkeypatch.setattr(openai_ai, "list_models", fake_list)
    body = c.post("/api/config/test/openai", json={"values": {"api_key": "sk-bad"}}).json()

    assert body["ok"] is False and "401" in body["detail"]


def test_a_network_failure_does_not_echo_the_request_back(client, monkeypatch):
    """A raw exception string can carry the URL, and a URL can carry a key. The
    handler reports a fixed sentence instead."""
    c, _ = client

    async def fake_list(key, *, transport=None):
        raise RuntimeError("connect failed: https://api.openai.com/v1/models?key=sk-secret")

    monkeypatch.setattr(openai_ai, "list_models", fake_list)
    body = c.post("/api/config/test/openai", json={"values": {"api_key": "sk-secret"}}).json()

    assert body["ok"] is False
    assert "sk-secret" not in body["detail"]


def test_health_names_the_engine_that_is_actually_live(settings):
    """This line used to say "Anthropic" whenever anything was configured. Naming
    the wrong provider is worse than naming none: it sends someone to check a key
    that was never in play."""
    from sift.services.health import _ai_health

    _with(settings, openai="sk-oai")
    assert _ai_health(settings).detail == "OpenAI"

    _with(settings, anthropic="sk-ant", local=True)
    assert _ai_health(settings).detail == "Anthropic + Ollama"

    _with(settings, local=True, mode="ollama")
    assert _ai_health(settings).detail == "Ollama"

    _with(settings)
    status = _ai_health(settings)
    assert status.ok is False and status.detail == "not configured"
