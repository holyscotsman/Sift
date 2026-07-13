"""Contract tests for the four source clients against a mock transport."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from sift.clients.plex import PlexClient
from sift.clients.radarr import RadarrClient
from sift.clients.tautulli import TautulliClient
from sift.clients.tmdb import TmdbClient
from sift.config import PlexConfig, RadarrConfig, TautulliConfig, TmdbConfig


async def _noop_sleep(_seconds: float) -> None:
    return None


async def test_radarr_movies_and_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "rk"
        if request.url.path == "/api/v3/system/status":
            return httpx.Response(200, json={"version": "5.2.6"})
        if request.url.path == "/api/v3/movie":
            return httpx.Response(200, json=[{"id": 1, "tmdbId": 603, "title": "The Matrix"}])
        return httpx.Response(404)

    cfg = RadarrConfig(base_url="http://radarr", api_key=SecretStr("rk"))
    client = RadarrClient(cfg, transport=httpx.MockTransport(handler), sleep=_noop_sleep)
    movies = await client.get_movies()
    assert movies[0]["tmdbId"] == 603
    health = await client.health()
    assert health.ok and "5.2.6" in health.detail
    await client.aclose()


async def test_plex_sections_items_and_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Plex-Token"] == "pt"
        assert "application/json" in request.headers["Accept"]
        path = request.url.path
        if path == "/identity":
            return httpx.Response(200, json={"MediaContainer": {"version": "1.40"}})
        if path == "/library/sections":
            return httpx.Response(
                200,
                json={
                    "MediaContainer": {
                        "Directory": [{"key": "1", "type": "movie", "title": "Movies"}]
                    }
                },
            )
        if path == "/library/sections/1/all":
            return httpx.Response(
                200,
                json={
                    "MediaContainer": {
                        "totalSize": 1,
                        "Metadata": [{"ratingKey": 10, "title": "M"}],
                    }
                },
            )
        return httpx.Response(404)

    cfg = PlexConfig(base_url="http://plex", token=SecretStr("pt"))
    client = PlexClient(cfg, transport=httpx.MockTransport(handler), sleep=_noop_sleep)
    sections = await client.get_sections()
    assert sections[0]["title"] == "Movies"
    items = await client.get_section_items("1")
    assert items[0]["ratingKey"] == 10
    assert (await client.health()).ok
    await client.aclose()


async def test_tautulli_history_and_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["apikey"] == "tk"
        cmd = request.url.params["cmd"]
        if cmd == "get_server_info":
            return httpx.Response(200, json={"response": {"result": "success", "data": {}}})
        if cmd == "get_history":
            return httpx.Response(
                200,
                json={
                    "response": {
                        "result": "success",
                        "data": {"recordsFiltered": 1, "data": [{"rating_key": 10, "user": "Dad"}]},
                    }
                },
            )
        return httpx.Response(404)

    cfg = TautulliConfig(base_url="http://taut", api_key=SecretStr("tk"))
    client = TautulliClient(cfg, transport=httpx.MockTransport(handler), sleep=_noop_sleep)
    rows = await client.get_history()
    assert rows[0]["rating_key"] == 10
    assert (await client.health()).ok
    await client.aclose()


async def test_tmdb_uses_api_key_and_language():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "mk"
        assert request.url.params["language"] == "en-US"
        if request.url.path == "/configuration":
            return httpx.Response(200, json={"images": {}})
        if request.url.path == "/movie/603":
            return httpx.Response(200, json={"id": 603, "title": "The Matrix"})
        return httpx.Response(404)

    cfg = TmdbConfig(api_key=SecretStr("mk"))
    client = TmdbClient(
        cfg, base_url="http://tmdb.test", transport=httpx.MockTransport(handler), sleep=_noop_sleep
    )
    movie = await client.get_movie(603)
    assert movie["title"] == "The Matrix"
    assert (await client.health()).ok
    await client.aclose()


async def test_tmdb_v4_bearer_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bearer eyJ")
        assert "api_key" not in request.url.params
        return httpx.Response(200, json={})

    cfg = TmdbConfig(api_key=SecretStr("eyJhbGci.payload.sig"))
    client = TmdbClient(
        cfg, base_url="http://tmdb.test", transport=httpx.MockTransport(handler), sleep=_noop_sleep
    )
    assert (await client.health()).ok
    await client.aclose()
