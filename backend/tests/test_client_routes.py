"""Every path the browser calls must exist on the server.

This is the one seam neither suite covers. The frontend tests mock `api`
wholesale — that is what makes them fast and what makes them blind to the
strings inside it — and the backend tests never see the client at all. So a
renamed or removed route is a 404 that appears only in a real browser, on the
one screen nobody opened before shipping.

The comparison is structural rather than clever: pull the paths out of the
client, pull the routes off the app, and require the first to be a subset of the
second.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sift.main import create_app

API_CLIENT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"

_CALL_PATTERNS = (
    r"request<[^>]*>\(\s*`([^`]*)`",
    r'request<[^>]*>\(\s*"([^"]*)"',
    r"request<[^>]*>\(\s*'([^']*)'",
)


def _collapse(literal: str) -> str:
    """`/api/movies/${id}/keep` -> `/api/movies/{}/keep`.

    Written as a scanner rather than a regex because a `${...}` expression can
    contain quotes and braces of its own — `${q ? "?" + q : ""}` is real code in
    this client, and a non-greedy regex silently truncates the path there.
    """
    out: list[str] = []
    i = 0
    while i < len(literal):
        if literal.startswith("${", i):
            depth, i = 1, i + 2
            while i < len(literal) and depth:
                if literal[i] == "{":
                    depth += 1
                elif literal[i] == "}":
                    depth -= 1
                i += 1
            out.append("{}")
        else:
            out.append(literal[i])
            i += 1
    return "".join(out)


def client_paths(source: str) -> set[str]:
    """Every API path the client asks for, normalised to the server's shape."""
    found: set[str] = set()
    for pattern in _CALL_PATTERNS:
        for match in re.finditer(pattern, source):
            path = _collapse(match.group(1)).split("?")[0]
            # A trailing `${...}` that does not follow a slash is an interpolated
            # query string (`/api/shows${queryString(q)}`); one that does is a
            # real path parameter and has to stay.
            while path.endswith("{}") and not path.endswith("/{}"):
                path = path[:-2]
            path = path.rstrip("/")
            if path.startswith(("/api", "/ws")):
                found.add(path)
    return found


def server_paths(settings, factory) -> set[str]:
    app = create_app(settings, session_factory=factory)
    routes: set[str] = set()

    def walk(items: object) -> None:
        for route in items or ():  # type: ignore[union-attr]
            path = getattr(route, "path", None)
            if isinstance(path, str) and path.startswith(("/api", "/ws")):
                routes.add(re.sub(r"\{[^}]+\}", "{}", path))
            nested = getattr(route, "routes", None)
            if nested is None:
                # FastAPI wraps included routers; the real routes hang off these.
                inner = getattr(route, "original_router", None)
                nested = getattr(inner, "routes", None) if inner is not None else None
            walk(nested)

    walk(app.routes)
    return routes


@pytest.mark.skipif(not API_CLIENT.is_file(), reason="frontend source not present")
def test_every_path_the_client_calls_exists_on_the_server(settings, factory) -> None:
    called = client_paths(API_CLIENT.read_text())
    served = server_paths(settings, factory)

    # A matcher that found nothing would satisfy the subset check perfectly.
    assert len(called) > 50, f"only {len(called)} client paths found — the matcher broke"
    assert len(served) > 50, f"only {len(served)} server routes found — the walk broke"

    missing = sorted(p for p in called if p not in served)
    assert not missing, "the client calls paths the server does not serve: " + ", ".join(missing)


def test_the_check_would_notice_a_renamed_route(settings, factory) -> None:
    """NEGATIVE CONTROL: prove the comparison can fail.

    A subset assertion passes trivially when one side is empty or when the
    normalisation quietly mangles both sides into agreement. Feed it a client
    that calls a route nobody serves and require it to be reported.
    """
    served = server_paths(settings, factory)
    # Deliberately a name no plausible refactor would ever introduce: if the
    # control shared a name with a real route, a rename could make the control
    # itself pass or fail for the wrong reason.
    invented = client_paths('request<Thing>("/api/no-such-route-exists-here")')

    assert invented == {"/api/no-such-route-exists-here"}
    assert not invented <= served


def test_path_parameters_survive_normalisation() -> None:
    """NEGATIVE CONTROL: the normaliser must not flatten paths into each other.

    Stripping a trailing `${...}` is right for an interpolated query string and
    wrong for a path parameter — get that backwards and `/api/config/test/{}`
    becomes `/api/config/test`, which matches nothing and reads as a false alarm
    (or, worse, matches something else and hides a real one).
    """
    assert client_paths("request<X>(`/api/config/test/${service}`)") == {"/api/config/test/{}"}
    assert client_paths("request<X>(`/api/shows${queryString(q)}`)") == {"/api/shows"}
    assert client_paths('request<X>(`/api/movies/${id}/keep`)') == {"/api/movies/{}/keep"}
    # The awkward one: a ternary with quotes and braces inside the expression.
    assert client_paths('request<X>(`/api/junk${q ? "?q=" + q : ""}`)') == {"/api/junk"}
