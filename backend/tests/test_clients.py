"""Contract tests for the source clients against a mock transport."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from sift.clients.plex import PlexClient
from sift.clients.radarr import RadarrClient
from sift.clients.sonarr import SonarrClient
from sift.clients.tautulli import TautulliClient
from sift.clients.tmdb import TmdbClient
from sift.config import (
    PlexConfig,
    RadarrConfig,
    SonarrConfig,
    TautulliConfig,
    TmdbConfig,
)


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
            # Must request the Guid array so tmdb ids resolve on modern agents.
            assert request.url.params.get("includeGuids") == "1"
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


async def test_sonarr_series_episodes_and_health():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "sk"
        path = request.url.path
        if path == "/api/v3/system/status":
            return httpx.Response(200, json={"version": "4.0.9"})
        if path == "/api/v3/series":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "tvdbId": 121361,
                        "title": "Game of Thrones",
                        "seasons": [
                            {
                                "seasonNumber": 1,
                                "statistics": {
                                    "sizeOnDisk": 40_000_000_000,
                                    "episodeFileCount": 10,
                                },
                            }
                        ],
                    }
                ],
            )
        if path == "/api/v3/episode":
            assert request.url.params["seriesId"] == "7"
            return httpx.Response(200, json=[{"id": 1, "episodeNumber": 1, "episodeFileId": 55}])
        if path == "/api/v3/episodefile":
            assert request.url.params["seriesId"] == "7"
            return httpx.Response(200, json=[{"id": 55, "size": 4_000_000_000}])
        return httpx.Response(404)

    cfg = SonarrConfig(base_url="http://sonarr", api_key=SecretStr("sk"))
    client = SonarrClient(cfg, transport=httpx.MockTransport(handler), sleep=_noop_sleep)

    series = await client.get_series()
    assert series[0]["tvdbId"] == 121361
    assert series[0]["seasons"][0]["statistics"]["sizeOnDisk"] == 40_000_000_000

    assert (await client.get_episodes(7))[0]["episodeFileId"] == 55
    assert (await client.get_episode_files(7))[0]["size"] == 4_000_000_000

    health = await client.health()
    assert health.ok and "4.0.9" in health.detail
    await client.aclose()


async def test_sonarr_without_a_url_is_not_configured_rather_than_broken():
    """NEGATIVE CONTROL: an unconfigured optional service must raise the error the
    scanner already treats as \"skip this one\", not construct a client that fails
    later inside a phase and takes the whole scan down."""
    import pytest

    from sift.clients.base import ClientError

    with pytest.raises(ClientError):
        SonarrClient(SonarrConfig())
