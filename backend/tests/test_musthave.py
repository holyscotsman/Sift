"""Must-Have engine: parsing, the anti-nonsense gates, dedupe, and the endpoints.

The gates are the contract: an AI proposal is only a hint, and nothing is stored
unless TMDB's data clears it. Each gate has a candidate designed to fail it.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sift.ai import musthave
from sift.ai.provider import Completion
from sift.db.models import CuratedListEntry, Movie, MustHaveSuggestion
from sift.main import create_app

# ---------------------------------------------------------------------- parsing


def test_parse_titles_tolerates_fences_and_garbage():
    text = (
        "Here you go!\n```json\n"
        '[{"title": "Seven Samurai", "year": 1954, "reason": "Essential."},'
        ' {"nonsense": true}, "not-a-dict",'
        ' {"title": "M", "year": 1931.0, "reason": ""}]\n```'
    )
    titles = musthave.parse_titles(text)
    assert [t["title"] for t in titles] == ["Seven Samurai", "M"]
    assert titles[0]["year"] == 1954 and titles[1]["year"] == 1931


def test_parse_titles_rejects_non_json():
    assert musthave.parse_titles("I suggest some movies you may enjoy!") == []


# ------------------------------------------------------------------- fake engine


class FakeProvider:
    """Stands in for either provider; returns a canned JSON list."""

    name = "fake"
    model = "fake"

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def complete(self, *, system: str, prompt: str) -> Completion:
        return Completion(text=self._payload, provider="anthropic", model="m", latency_ms=1.0)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


# One candidate per gate, plus one that passes everything.
_PROPOSAL = """[
  {"title": "Seven Samurai", "year": 1954, "reason": "Kurosawa's essential epic."},
  {"title": "Totally Made Up Film", "year": 2001, "reason": "Hallucinated."},
  {"title": "Fringe Upload", "year": 2020, "reason": "Nobody has voted on it."},
  {"title": "Beloved Short", "year": 2010, "reason": "Only 12 minutes long."},
  {"title": "Future Epic", "year": 2030, "reason": "Not released yet."},
  {"title": "Owned Classic", "year": 1999, "reason": "Already in Plex."},
  {"title": "Mediocre Filler", "year": 2005, "reason": "Scores 5.1."}
]"""

_DETAILS = {
    11: {"title": "Seven Samurai", "vote_count": 9000, "vote_average": 8.6, "runtime": 207,
         "release_date": "1954-04-26", "adult": False},
    13: {"title": "Fringe Upload", "vote_count": 12, "vote_average": 9.9, "runtime": 100,
         "release_date": "2020-01-01", "adult": False},
    14: {"title": "Beloved Short", "vote_count": 5000, "vote_average": 8.0, "runtime": 12,
         "release_date": "2010-01-01", "adult": False},
    15: {"title": "Future Epic", "vote_count": 5000, "vote_average": 9.0, "runtime": 150,
         "release_date": "2099-01-01", "adult": False},
    16: {"title": "Owned Classic", "vote_count": 5000, "vote_average": 8.0, "runtime": 120,
         "release_date": "1999-01-01", "adult": False},
    17: {"title": "Mediocre Filler", "vote_count": 5000, "vote_average": 5.1, "runtime": 110,
         "release_date": "2005-01-01", "adult": False},
}
_SEARCH = {
    "Seven Samurai": 11,
    "Fringe Upload": 13,
    "Beloved Short": 14,
    "Future Epic": 15,
    "Owned Classic": 16,
    "Mediocre Filler": 17,
}


def _tmdb_handler(request: httpx.Request) -> httpx.Response:
    # The client's base URL carries the /3 API prefix — match on suffixes.
    path = request.url.path
    if path.endswith("/search/movie"):
        query = request.url.params.get("query", "")
        tid = _SEARCH.get(query)
        return httpx.Response(200, json={"results": [{"id": tid}] if tid else []})
    if "/movie/" in path:
        tid = int(path.rsplit("/", 1)[1])
        detail = _DETAILS.get(tid)
        return httpx.Response(200, json=detail) if detail else httpx.Response(404)
    return httpx.Response(404)


@pytest.fixture
def tmdb_settings(settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    return settings


async def test_gates_drop_everything_but_the_real_canon(tmdb_settings, factory, monkeypatch):
    with factory() as session:
        session.add(Movie(tmdb_id=16, title="Owned Classic", in_plex=True))
        session.commit()
    monkeypatch.setattr(
        musthave, "build_providers", lambda _s: (None, FakeProvider(_PROPOSAL))
    )

    result = await musthave.run_musthave(
        factory, tmdb_settings, limit=10, transport=httpx.MockTransport(_tmdb_handler)
    )

    assert result["added"] == 1 and result["provider"] == "anthropic"
    with factory() as session:
        rows = session.query(MustHaveSuggestion).all()
        assert [r.tmdb_id for r in rows] == [11]
        assert rows[0].title == "Seven Samurai"
        assert rows[0].vote_count == 9000


async def test_rerun_never_duplicates_and_respects_dismissed(
    tmdb_settings, factory, monkeypatch
):
    monkeypatch.setattr(
        musthave, "build_providers", lambda _s: (None, FakeProvider(_PROPOSAL))
    )
    transport = httpx.MockTransport(_tmdb_handler)
    first = await musthave.run_musthave(factory, tmdb_settings, transport=transport)
    # Nothing is owned in this test, so the un-owned "Owned Classic" also clears.
    assert first["added"] == 2
    # Dismiss one, then run again — nothing comes back, nothing duplicates.
    with factory() as session:
        row = session.query(MustHaveSuggestion).filter_by(tmdb_id=11).one()
        row.status = "dismissed"
        session.commit()
    second = await musthave.run_musthave(factory, tmdb_settings, transport=transport)
    assert second["added"] == 0
    with factory() as session:
        assert session.query(MustHaveSuggestion).count() == 2


async def test_curated_fallback_without_ai(tmdb_settings, factory, monkeypatch):
    # No providers configured → the starter lists feed the same gates.
    with factory() as session:
        session.add(
            CuratedListEntry(list_name="criterion", title="Seven Samurai", year=1954)
        )
        session.commit()
    monkeypatch.setattr(musthave, "build_providers", lambda _s: (None, None))

    result = await musthave.run_musthave(
        factory, tmdb_settings, transport=httpx.MockTransport(_tmdb_handler)
    )
    assert result["provider"] == "curated" and result["added"] == 1
    with factory() as session:
        row = session.query(MustHaveSuggestion).one()
        assert "starter list" in row.reason


async def test_without_tmdb_the_run_declines(settings, factory):
    settings.tmdb.enabled = False
    result = await musthave.run_musthave(factory, settings)
    assert result["added"] == 0 and "TMDB" in result.get("note", "")


# ------------------------------------------------------------------- endpoints


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c


def test_musthave_endpoints_list_and_dismiss(client, factory):
    with factory() as session:
        session.add(
            MustHaveSuggestion(
                tmdb_id=11, title="Seven Samurai", year=1954, reason="Essential.",
                source="anthropic", vote_average=8.6, vote_count=9000,
            )
        )
        # An owned title never shows even if a row exists.
        session.add(
            MustHaveSuggestion(tmdb_id=16, title="Owned Classic", year=1999, source="x")
        )
        session.add(Movie(tmdb_id=16, title="Owned Classic", in_plex=True))
        session.commit()

    items = client.get("/api/musthave").json()["items"]
    assert [i["tmdb_id"] for i in items] == [11]

    sid = items[0]["id"]
    assert client.post(f"/api/musthave/{sid}/dismiss").status_code == 200
    assert client.get("/api/musthave").json()["items"] == []
    assert client.post("/api/musthave/999/dismiss").status_code == 404
