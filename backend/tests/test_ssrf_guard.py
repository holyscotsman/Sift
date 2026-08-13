"""A service URL must not be usable to fetch the deploy's own credentials.

Sift stores an API key per service and sends it to whatever base URL is
configured. Every major cloud serves instance credentials from a link-local
address with no authentication, so pointing a service at one turns "test my
connection" into "read this deploy's keys", with the answer returned through the
health endpoint. Sift runs on Render, so this is not hypothetical.

Private ranges are deliberately allowed: Plex and Radarr live on a home LAN, and
refusing 192.168.x.x would break the product's normal configuration while
defending against nothing.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from sift.clients.base import ClientError
from sift.clients.radarr import RadarrClient
from sift.config import RadarrConfig


def _client(base_url: str) -> RadarrClient:
    return RadarrClient(
        RadarrConfig(base_url=base_url, api_key=SecretStr("secret")),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254",            # AWS / Azure / DigitalOcean IMDS
        "http://169.254.169.254:80/latest",
        "http://[::ffff:169.254.169.254]",   # the same address wearing a hat
        "http://metadata.google.internal",
        "http://metadata.goog/computeMetadata/v1/",
        "https://169.254.170.2",             # ECS task credentials
    ],
)
def test_credentials_are_not_sent_to_an_instance_metadata_endpoint(url):
    with pytest.raises(ClientError):
        _client(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x", "ftp://host"])
def test_only_http_urls_are_accepted(url):
    with pytest.raises(ClientError):
        _client(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.50:7878",   # the ordinary case: a box on the LAN
        "http://10.0.0.4:7878",
        "http://172.16.5.5:7878",
        "http://radarr.local:7878",
        "http://localhost:7878",      # docker-compose puts them side by side
        "http://127.0.0.1:7878",
        "https://radarr.example.com",
    ],
)
def test_a_normal_home_setup_is_left_alone(url):
    """NEGATIVE CONTROL, and the more important half.

    A guard that blocks private addresses would pass every test above and make the
    product unusable, since the media server is *supposed* to be on the LAN. These
    must all still construct.
    """
    client = _client(url)
    assert client.service == "radarr"
