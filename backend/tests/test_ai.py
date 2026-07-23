"""AI provider layer + grounded query (deterministic stub — no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.ai import query as ai_query
from sift.ai.provider import StubProvider
from sift.ai.registry import ai_configured, build_llm_provider
from sift.db.models import Movie
from sift.main import create_app


def test_registry_falls_back_to_stub_without_key(settings, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai_configured(settings) is False
    provider = build_llm_provider(settings)
    assert isinstance(provider, StubProvider)


def test_registry_uses_ui_entered_key(settings, monkeypatch):
    from pydantic import SecretStr

    from sift.ai.anthropic import AnthropicProvider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings.ai.anthropic_api_key = SecretStr("sk-ui-entered")
    assert ai_configured(settings) is True
    assert isinstance(build_llm_provider(settings), AnthropicProvider)


def _configure_both(settings, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings.ai.anthropic_api_key = SecretStr("sk-x")
    settings.ai.local_enabled = True


def test_engine_mode_tandem_builds_both(settings, monkeypatch):
    from sift.ai.registry import build_providers

    _configure_both(settings, monkeypatch)
    settings.ai.mode = "tandem"
    local, remote = build_providers(settings)
    assert local is not None and remote is not None


def test_engine_mode_anthropic_suppresses_local(settings, monkeypatch):
    from sift.ai.anthropic import AnthropicProvider
    from sift.ai.registry import build_providers

    _configure_both(settings, monkeypatch)
    settings.ai.mode = "anthropic"
    local, remote = build_providers(settings)
    assert local is None and remote is not None
    assert isinstance(build_llm_provider(settings), AnthropicProvider)


def test_engine_mode_ollama_suppresses_anthropic_and_answers_ask(settings, monkeypatch):
    # Local-only mode: even with a key present, everything (Ask included) stays local.
    from sift.ai.ollama import OllamaProvider
    from sift.ai.registry import build_providers

    _configure_both(settings, monkeypatch)
    settings.ai.mode = "ollama"
    local, remote = build_providers(settings)
    assert remote is None and local is not None
    assert isinstance(build_llm_provider(settings), OllamaProvider)
    assert ai_configured(settings) is True


def test_engine_mode_ollama_without_local_is_unconfigured(settings, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings.ai.anthropic_api_key = SecretStr("sk-x")
    settings.ai.local_enabled = False
    settings.ai.mode = "ollama"
    assert ai_configured(settings) is False
    assert isinstance(build_llm_provider(settings), StubProvider)


async def test_stub_completion_is_deterministic():
    p = StubProvider()
    a = await p.complete(system="s", prompt="p")
    b = await p.complete(system="s", prompt="p2")
    assert a.text == b.text
    assert "Settings" in a.text  # points at the in-app Connections, not an env var


def test_ask_degrades_instead_of_500_when_provider_errors(settings, factory, monkeypatch):
    # A saved-but-dead provider (e.g. an unreachable Ollama URL) must not turn Ask
    # into a 500 — the route falls back to grounded sources with a plain message.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.ai.local_enabled = True
    settings.ai.local_base_url = "http://127.0.0.1:1"  # nothing listens here
    settings.ai.mode = "ollama"
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client, factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", in_plex=True))
        session.commit()
        resp = client.post("/api/ask", json={"query": "matrix"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["provider"] == "error"
        assert any(s["tmdb_id"] == 603 for s in body["sources"])


def test_retrieve_matches_library_titles(factory):
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.add(Movie(tmdb_id=862, title="Toy Story", year=1995, in_plex=True))
        session.commit()
        hits = ai_query.retrieve(session, "matrix")
        assert [m.tmdb_id for m in hits] == [603]


async def test_answer_is_grounded_with_sources(factory):
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.commit()
        result = await ai_query.answer(session, StubProvider(), "tell me about the matrix")
    assert result.provider == "stub"
    assert [s.tmdb_id for s in result.sources] == [603]


@pytest.fixture
def client(settings, factory, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_ask_endpoint(client):
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.commit()
    body = c.post("/api/ask", json={"query": "the matrix"}).json()
    assert body["ai_configured"] is False
    assert body["provider"] == "stub"
    assert any(s["tmdb_id"] == 603 for s in body["sources"])


def test_ask_compare_returns_both_answers(client, monkeypatch):
    # Compare mode: one retrieval, two phrasings, both labeled. The alternate is
    # built per-request; here both are stubs with distinct models.
    from sift.api import routes_ask

    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.commit()
    monkeypatch.setattr(routes_ask, "_build_alternate", lambda settings: StubProvider("local"))
    body = c.post("/api/ask", json={"query": "the matrix", "mode": "compare"}).json()
    assert body["alternate"] is not None
    assert body["alternate"]["model"] == "local"
    assert body["alternate"]["answer"]
    assert any(s["tmdb_id"] == 603 for s in body["sources"])


def test_ask_compare_degrades_when_alternate_fails(client, monkeypatch):
    from sift.api import routes_ask

    class ExplodingProvider:
        name = "boom"
        model = "boom"

        async def complete(self, *, system: str, prompt: str):
            raise RuntimeError("dead provider")

        async def aclose(self) -> None:
            return None

    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.commit()
    monkeypatch.setattr(routes_ask, "_build_alternate", lambda settings: ExplodingProvider())
    body = c.post("/api/ask", json={"query": "the matrix", "mode": "compare"}).json()
    # Primary answer survives; the dead alternate is simply absent.
    assert body["provider"] == "stub"
    assert body["alternate"] is None


def test_ask_single_mode_has_no_alternate(client):
    # Negative control: default mode never carries a second answer.
    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=603, title="The Matrix", year=1999, in_plex=True))
        session.commit()
    body = c.post("/api/ask", json={"query": "the matrix"}).json()
    assert body["alternate"] is None
