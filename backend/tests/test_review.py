"""AI review orchestration (Ollama ↔ Anthropic) with fake providers — no network."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.ai import review as ai_review
from sift.ai.provider import Completion
from sift.analysis import junk
from sift.config import JunkThresholds
from sift.db.models import Movie, Rating, RatingSource
from sift.main import create_app


class Fake:
    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.model = "m"
        self._text = text
        self.closed = False

    async def complete(self, *, system: str, prompt: str) -> Completion:
        return Completion(text=self._text, provider=self.name, model="m", latency_ms=1.0)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


_TARGET = {"title": "Flop", "year": 2001, "genres": ["Drama"], "score": 70, "reason": "because"}


async def test_local_only_uses_draft():
    note = await ai_review.review_one(_TARGET, local=Fake("ollama", "draft"), anthropic=None)
    assert note.provider == "ollama" and note.note == "draft"


async def test_anthropic_only():
    note = await ai_review.review_one(_TARGET, local=None, anthropic=Fake("anthropic", "final"))
    assert note.provider == "anthropic" and note.note == "final"


async def test_both_anthropic_refines_local():
    note = await ai_review.review_one(
        _TARGET, local=Fake("ollama", "draft"), anthropic=Fake("anthropic", "final")
    )
    assert note.provider == "anthropic+ollama" and note.note == "final"


async def test_neither_falls_back_to_deterministic():
    note = await ai_review.review_one(_TARGET, local=None, anthropic=None)
    assert note.provider == "deterministic" and note.note == "because"


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def test_review_run_endpoint_stores_notes(client):
    c, factory = client
    with factory() as session:
        m = Movie(tmdb_id=603, title="Junk Film", in_plex=True)
        m.ratings.append(Rating(source=RatingSource.IMDB, value=3.0, votes=200))
        session.add(m)
        session.commit()
    junk.compute_and_store(factory, JunkThresholds())

    # No AI configured → deterministic provider, but a note is still written.
    run = c.post("/api/review/run").json()
    assert run["reviewed"] == 1 and run["provider"] == "deterministic"

    item = c.get("/api/junk").json()["items"][0]
    assert item["ai_note"]  # populated
