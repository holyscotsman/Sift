"""The Sonarr write-back — the guard that stops a downgrade being undone.

`set_quality_profile` is the piece the design notes call non-negotiable, and it
was uncovered. Its own docstring states the reason: a season left pointing at a
high cutoff is re-fetched by Sonarr's next search, so the space comes back and is
quietly spent again. Applying a downgrade without writing this back is *worse*
than doing nothing — it costs the picture and keeps the disk.

Also covers the two Overseerr calls and Sonarr's remaining edges, which are the
boundary with a service that can answer anything at all.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from sift.clients.base import ClientError
from sift.clients.overseerr import OverseerrClient
from sift.clients.sonarr import SonarrClient
from sift.config import OverseerrConfig, SonarrConfig

SERIES = {
    "id": 12,
    "title": "Scrubs",
    "tvdbId": 76156,
    "qualityProfileId": 4,
    "monitored": True,
    "seasons": [{"seasonNumber": 1, "monitored": True}],
    "path": "/tv/Scrubs",
}


async def _noop_sleep(_seconds: float) -> None:
    return None


def _sonarr(handler):
    return SonarrClient(
        SonarrConfig(base_url="http://sonarr", api_key=SecretStr("sk")),
        transport=httpx.MockTransport(handler),
        sleep=_noop_sleep,
    )


async def test_a_profile_change_is_staged_by_default():
    """Dry run is the default, and a staged change reaches no network at all.

    This is a write into the automation that manages the library. The same floor
    the delete path has applies: the caller opts *into* the live write, and a
    caller that forgot the argument stages rather than writes.
    """
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = _sonarr(handler)
    result = await client.set_quality_profile(SERIES, 2)
    await client.aclose()

    assert result == {"dry_run": True, "seriesId": 12, "qualityProfileId": 2}
    assert calls == []  # nothing was sent


async def test_a_live_change_sends_the_whole_series_back():
    """Sonarr's series endpoint is a whole-object PUT.

    Sending only the changed field is how a write-back silently unmonitors a show
    or blanks its path: everything absent from the payload is taken as the new
    value. The object Sonarr gave us goes back with one field changed.
    """
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/v3/series/12"
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": 12, "qualityProfileId": 2})

    client = _sonarr(handler)
    result = await client.set_quality_profile(SERIES, 2, dry_run=False)
    await client.aclose()

    assert result["qualityProfileId"] == 2
    body = sent[0]
    assert body["qualityProfileId"] == 2  # the one change
    assert body["monitored"] is True  # and everything else survives
    assert body["path"] == "/tv/Scrubs"
    assert body["seasons"] == SERIES["seasons"]
    assert body["title"] == "Scrubs"


async def test_the_original_series_object_is_not_mutated():
    """NEGATIVE CONTROL: the caller's copy keeps its old profile id.

    The payload is built with a spread rather than by assigning into the dict it
    was handed. Mutating in place would leave the caller believing the change had
    already applied even when the write was staged or failed.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = _sonarr(handler)
    await client.set_quality_profile(SERIES, 2, dry_run=False)
    await client.aclose()

    assert SERIES["qualityProfileId"] == 4


async def test_a_refused_write_raises_rather_than_reporting_success():
    """NEGATIVE CONTROL for the whole guard. A downgrade whose write-back failed
    must not look like one that applied — that is precisely the state the guard
    exists to prevent, and swallowing the error creates it deliberately.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "invalid profile"})

    client = _sonarr(handler)
    with pytest.raises(ClientError):
        await client.set_quality_profile(SERIES, 999, dry_run=False)
    await client.aclose()


async def test_quality_profiles_survive_an_unexpected_shape():
    """Sonarr answers with a list. Anything else is a proxy, a login page or an
    error body, and the right answer is an empty list rather than a crash in the
    middle of a scan.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/qualityprofile":
            return httpx.Response(200, json=[{"id": 4, "name": "HD-1080p"}])
        return httpx.Response(404)

    client = _sonarr(handler)
    profiles = await client.get_quality_profiles()
    await client.aclose()
    assert [p["name"] for p in profiles] == ["HD-1080p"]

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "not a list"})

    client = _sonarr(odd)
    assert await client.get_quality_profiles() == []
    assert await client.get_series() == []
    assert await client.get_episodes(12) == []
    assert await client.get_episode_files(12) == []
    await client.aclose()


async def test_an_unreachable_sonarr_is_a_status_not_an_exception():
    """Health is reported, never raised: a scan preflight asks every service and
    one being down must not end the sweep.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _sonarr(handler)
    status = await client.health()
    await client.aclose()

    assert status.ok is False
    assert status.service == "sonarr"
    assert "sk" not in status.detail  # the key is never in a message


async def test_overseerr_files_a_movie_request():
    """The add path when Overseerr is the front door: a request, not a direct
    Radarr add, so it flows through Overseerr's own approval and quality rules.
    """
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.headers["X-Api-Key"] == "ok"
        assert request.url.path == "/api/v1/request"
        sent.append(json.loads(request.content))
        return httpx.Response(201, json={"id": 7, "status": 1})

    client = OverseerrClient(
        OverseerrConfig(base_url="http://overseerr", api_key=SecretStr("ok")),
        transport=httpx.MockTransport(handler),
        sleep=_noop_sleep,
    )
    result = await client.request_movie(603)
    await client.aclose()

    assert result["id"] == 7
    assert sent[0] == {"mediaType": "movie", "mediaId": 603}


async def test_overseerr_probes_its_own_status_path():
    """NEGATIVE CONTROL on the health path: Overseerr is v1, not Radarr's v3.

    A client that inherited the default path would report every Overseerr as down,
    and the add button would silently fall back to Radarr on a working install.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"version": "1.33.2"})

    client = OverseerrClient(
        OverseerrConfig(base_url="http://overseerr", api_key=SecretStr("ok")),
        transport=httpx.MockTransport(handler),
        sleep=_noop_sleep,
    )
    status = await client.health()
    await client.aclose()

    assert status.ok is True
    assert seen == ["/api/v1/status"]
