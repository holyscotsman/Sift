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


# Two paths took a user-supplied URL and built their own httpx client, so neither
# ever passed through `BaseClient.__init__` and neither got the guard. Both are
# authenticated and one is blind, so neither is the worst of its kind — but the
# guard exists so that "refuse to send credentials to the metadata endpoint" is
# true *everywhere* rather than nearly everywhere, and a control with a hole in it
# is worse than one without, because everybody stops checking.


class TestTheOllamaProvider:
    """The saved-and-used path, which the *test* path already guarded.

    `routes_config` guards this exact URL before probing it, with a comment saying
    why: it "builds its own httpx client — so it was the one path that could be
    pointed at 169.254.169.254 and used as a reachability oracle". The provider
    that actually calls the saved URL on every scan had no such check, so a URL
    that failed the connection test could still be saved and then used.
    """

    def test_the_metadata_endpoint_is_refused(self):
        from sift.ai.ollama import OllamaProvider

        with pytest.raises(ClientError):
            OllamaProvider("http://169.254.169.254", "llama3.1")

    def test_an_ipv4_mapped_address_is_the_same_address(self):
        from sift.ai.ollama import OllamaProvider

        with pytest.raises(ClientError):
            OllamaProvider("http://[::ffff:169.254.169.254]", "llama3.1")

    def test_NEGATIVE_CONTROL_a_real_local_ollama_still_works(self):
        """Which is where Ollama actually lives. A guard that blocked private
        addresses here would block the only configuration anybody uses."""
        from sift.ai.ollama import OllamaProvider

        assert OllamaProvider("http://127.0.0.1:11434", "llama3.1").model == "llama3.1"
        assert OllamaProvider("http://192.168.1.20:11434", "llama3.1").model == "llama3.1"


class TestTheDeployHook:
    """A stored URL the server POSTs to on request is an SSRF primitive."""

    def test_a_hook_pointing_at_the_metadata_endpoint_is_refused(self, tmp_path, settings):
        from fastapi.testclient import TestClient

        from sift.db.session import init_db, make_engine, make_session_factory
        from sift.main import create_app
        from sift.services import auth, config_store

        engine = make_engine(tmp_path / "hook.db")
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            config_store.set_config(
                session, {"deploy": {"hook_url": "http://169.254.169.254/latest/meta-data/"}}
            )
            session.commit()
            auth.create_account(session, "owner", "hunter2hunter2")
            token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

        app = create_app(settings, session_factory=factory)
        with TestClient(app) as client:
            resp = client.post(
                "/api/system/update", headers={"Authorization": f"Bearer {token}"}
            )

        assert resp.status_code == 400
        assert "169.254.169.254" in resp.json()["detail"]

    def test_NEGATIVE_CONTROL_an_ordinary_hook_is_not_refused_by_the_guard(
        self, tmp_path, settings
    ):
        """The guard must not become the reason a real deploy hook stops working.

        A genuine Render hook is reachable from here in tests, so this asserts the
        *guard* did not fire: the request gets as far as trying to send, and fails
        on the network rather than on the URL.
        """
        from fastapi.testclient import TestClient

        from sift.db.session import init_db, make_engine, make_session_factory
        from sift.main import create_app
        from sift.services import auth, config_store

        engine = make_engine(tmp_path / "hook2.db")
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            config_store.set_config(
                session,
                {"deploy": {"hook_url": "https://api.render.com/deploy/srv-abc?key=xyz"}},
            )
            session.commit()
            auth.create_account(session, "owner", "hunter2hunter2")
            token = auth.issue_token(auth._signing_secret(auth.get_auth(session)) or "", "owner")

        app = create_app(settings, session_factory=factory)
        with TestClient(app) as client:
            resp = client.post(
                "/api/system/update", headers={"Authorization": f"Bearer {token}"}
            )

        # Either it reached the network and failed there, or it succeeded. What it
        # must not say is that the URL itself was refused.
        assert "refusing to send credentials" not in resp.text
