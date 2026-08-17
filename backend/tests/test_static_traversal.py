"""The SPA catch-all must serve the built UI and nothing else.

This route sits below the API gate — it is the only handler an anonymous caller
can reach — so a containment bug here is unauthenticated arbitrary file read on a
public instance. The pins below run against the real ASGI app rather than against
the path arithmetic, because the bug they replace passed every check that only
read the code.

**The probes are percent-encoded on purpose.** An HTTP client collapses a literal
``../`` before the request is sent, so a plain-text probe tests nothing at all —
it arrives at the handler already sanitised. ``%2e%2e`` survives the client, is
decoded by the server, and is *not* re-normalised, which is precisely the shape of
the real attack. ``test_the_probes_are_not_normalised_away`` exists to make sure
this file cannot quietly become decorative if that behaviour ever changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sift import main
from sift.main import create_app

# dist → frontend → site → tmp_path is three levels; the extra hops are harmless
# because `resolve()` collapses `..` at the filesystem root.
UP = "%2e%2e/"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake built frontend, with a secret sitting outside it."""
    root = tmp_path / "site" / "frontend" / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Sift</title>")
    (root / "favicon.svg").write_text("<svg/>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.env").write_text("SIFT_SECRET_KEY=hunter2")
    monkeypatch.setattr(main, "_FRONTEND_DIST", root)
    return root


@pytest.fixture
def client(dist: Path, factory, settings) -> TestClient:
    return TestClient(create_app(settings, session_factory=factory))


def test_the_probes_are_not_normalised_away() -> None:
    """This file's premise, pinned.

    If the stack ever starts collapsing ``%2e%2e`` before routing, every test
    below would still pass while testing nothing. This fails loudly instead.
    """
    app = FastAPI()
    seen: list[str] = []

    @app.get("/{full_path:path}")
    def echo(full_path: str) -> dict[str, str]:
        seen.append(full_path)
        return {"path": full_path}

    TestClient(app).get(f"/{UP}{UP}secret.env")
    assert seen == ["../../secret.env"], seen


@pytest.mark.parametrize(
    "attack",
    [
        UP * 3 + "secret.env",
        UP * 6 + "secret.env",
        "..%2f..%2f..%2fsecret.env",
        "assets/" + UP * 4 + "secret.env",
        UP * 12 + "etc/passwd",
        UP * 12 + "proc/self/environ",
    ],
)
def test_traversal_never_escapes_the_build_directory(client: TestClient, attack: str) -> None:
    """No path may reach a file outside dist.

    ``is_relative_to`` compares path *parts* and never resolves ``..``, while
    ``is_file()`` resolves it at the OS level — so the two together said yes to
    ``../../../etc/passwd``. On a hosted instance that made
    ``/proc/self/environ`` — the signing key, the database URL and every stored
    API key — a single anonymous GET away.
    """
    response = client.get(f"/{attack}")
    # Two safe answers exist and both are fine: the catch-all serves the SPA
    # fallback, and the /assets mount (which does its own containment) refuses
    # outright. What must never happen is the file coming back.
    assert "hunter2" not in response.text
    assert "root:x:" not in response.text
    if response.status_code == 200:
        assert response.text.startswith("<!doctype html>")
    else:
        assert response.status_code == 404


def test_real_build_files_are_still_served(client: TestClient) -> None:
    """NEGATIVE CONTROL: the fix must not break the thing the route is for.

    Refusing everything would satisfy the test above and ship a blank app. A file
    genuinely inside dist still has to come back as itself, not as the fallback.
    """
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_client_routes_still_fall_back_to_index(client: TestClient) -> None:
    """NEGATIVE CONTROL: a deep-linked SPA route is not a file and must return
    index.html — the reason the catch-all exists at all."""
    response = client.get("/library")
    assert response.status_code == 200
    assert response.text.startswith("<!doctype html>")


def test_api_paths_are_not_swallowed_by_the_catch_all(client: TestClient) -> None:
    """An unknown /api path stays a 404 rather than quietly returning the UI."""
    assert client.get("/api/nope").status_code == 404
