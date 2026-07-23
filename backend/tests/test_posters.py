"""Poster resolution + on-disk cache, and the token-gated /api/poster route."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sift.db.models import Movie
from sift.main import create_app
from sift.services.posters import PosterCache

_JPEG = b"\xff\xd8\xffSIFTFAKEJPEG"


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.themoviedb.org" in url and "/movie/" in url:
            return httpx.Response(200, json={"poster_path": "/resolved.jpg"})
        if "image.tmdb.org" in url:
            return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def cache(settings, factory, tmp_path):
    settings.posters.cache_dir = tmp_path
    settings.tmdb.api_key = SecretStr("k")  # enable the TMDB-lookup path
    return PosterCache(settings, factory, transport=_transport())


async def test_serves_from_stored_url(cache, factory):
    with factory() as session:
        session.add(
            Movie(tmdb_id=603, title="The Matrix", in_plex=True,
                  poster_url="https://image.tmdb.org/t/p/w342/stored.jpg")
        )
        session.commit()

    path = await cache.get(603)
    assert path is not None and path.read_bytes() == _JPEG
    # Second call is a pure cache hit (file already present).
    assert cache.cached(603) is not None


async def test_resolves_via_tmdb_when_no_stored_url(cache, factory):
    # A Plex-only title with no artwork → resolved by id through TMDB, then persisted.
    with factory() as session:
        session.add(Movie(tmdb_id=27205, title="Inception", in_plex=True))
        session.commit()

    path = await cache.get(27205)
    assert path is not None and path.read_bytes() == _JPEG
    with factory() as session:
        assert session.get(Movie, 27205).poster_url == "https://image.tmdb.org/t/p/w342/resolved.jpg"


async def test_none_when_unresolvable(settings, factory, tmp_path):
    # NEGATIVE CONTROL: no stored url and TMDB disabled → no poster (UI placeholder).
    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = False
    plain = PosterCache(settings, factory, transport=_transport())
    with factory() as session:
        session.add(Movie(tmdb_id=999, title="Obscure", in_plex=True))
        session.commit()
    assert await plain.get(999) is None


def test_poster_endpoint_token_gated(settings, factory, tmp_path):
    settings.server.api_token = SecretStr("tok")
    settings.posters.cache_dir = tmp_path
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    with factory() as session:
        session.add(
            Movie(tmdb_id=603, title="The Matrix", in_plex=True,
                  poster_url="https://image.tmdb.org/t/p/w342/stored.jpg")
        )
        session.commit()

    app = create_app(settings, session_factory=factory)
    # Swap in a mock-transport cache so the endpoint never hits the network.
    app.state.sift.posters = PosterCache(settings, factory, transport=_transport())
    with TestClient(app) as c:
        assert c.get("/api/poster/603").status_code == 401  # no token
        ok = c.get("/api/poster/603", params={"token": "tok"})  # token via query (img-friendly)
        assert ok.status_code == 200 and ok.content == _JPEG
        # Header token works too.
        assert c.get("/api/poster/603", headers={"X-Sift-Token": "tok"}).status_code == 200
        # Unknown id with sources disabled → 404 (placeholder on the client).
        assert c.get("/api/poster/111", params={"token": "tok"}).status_code == 404


def test_poster_stats_and_clear_endpoints(settings, factory, tmp_path):
    from fastapi.testclient import TestClient

    from sift.main import create_app

    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    settings.posters.cache_dir = tmp_path
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        token = client.post(
            "/api/auth/setup", json={"username": "alice", "password": "hunter2hunter2"}
        ).json()["token"]
        headers = {"X-Sift-Token": token}

        # Empty cache → zeros; endpoints are gated.
        assert client.get("/api/posters/stats").status_code == 401
        assert client.get("/api/posters/stats", headers=headers).json() == {
            "count": 0,
            "bytes": 0,
        }

        # Drop two fake cached posters and watch the numbers move.
        posters_dir = tmp_path / "posters"
        posters_dir.mkdir(parents=True, exist_ok=True)
        (posters_dir / "1.img").write_bytes(b"x" * 10)
        (posters_dir / "2.img").write_bytes(b"y" * 5)
        stats = client.get("/api/posters/stats", headers=headers).json()
        assert stats == {"count": 2, "bytes": 15}

        cleared = client.post("/api/posters/clear", headers=headers).json()
        assert cleared["count"] == 2  # how many files were removed
        assert client.get("/api/posters/stats", headers=headers).json() == {
            "count": 0,
            "bytes": 0,
        }
