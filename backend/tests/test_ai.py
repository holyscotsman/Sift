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


async def test_stub_completion_is_deterministic():
    p = StubProvider()
    a = await p.complete(system="s", prompt="p")
    b = await p.complete(system="s", prompt="p2")
    assert a.text == b.text
    assert "ANTHROPIC_API_KEY" in a.text


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
