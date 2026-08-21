"""The version check behind the Update button.

The comparison arithmetic and the offline case are pinned in `test_system.py`.
What was not is everything between: the successful fetch, the cache that keeps an
idle instance from hammering GitHub, and the fallback that decides what a *later*
failure is allowed to do to an answer already held.

That last one matters more than it looks. This is the only thing that tells the
owner an update exists, and the button it feeds is what invalidates every chunk
hash in an open tab — so "there is an update" needs to be true when it says so,
and "I could not check" needs to be distinguishable from "you are current".
"""

from __future__ import annotations

import pytest

from sift.services import updates

PYPROJECT = '[project]\nname = "sift"\nversion = "2607.99.0"\ndescription = "x"\n'


class FakeClient:
    """Stands in for `httpx.AsyncClient`, recording every URL it is asked for."""

    calls: list[str] = []
    body: str = PYPROJECT
    status_error: Exception | None = None

    def __init__(self, **_kw: object) -> None:
        pass

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False

    async def get(self, url: str) -> FakeClient:
        FakeClient.calls.append(url)
        return self

    def raise_for_status(self) -> None:
        if FakeClient.status_error:
            raise FakeClient.status_error

    @property
    def text(self) -> str:
        return FakeClient.body


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    updates.reset_cache()
    FakeClient.calls = []
    FakeClient.body = PYPROJECT
    FakeClient.status_error = None
    monkeypatch.setattr(updates.httpx, "AsyncClient", FakeClient)
    monkeypatch.delenv("SIFT_UPDATE_REPO", raising=False)
    yield
    updates.reset_cache()


async def test_the_published_version_is_read_from_the_repository():
    assert await updates.latest_version() == "2607.99.0"
    assert FakeClient.calls == [
        "https://raw.githubusercontent.com/holyscotsman/Sift/main/pyproject.toml"
    ]


async def test_a_second_check_inside_the_hour_asks_nobody():
    """The Settings page polls, and every open tab on every instance would
    otherwise be a request to GitHub. The upstream version moves when a release
    merges, not minute to minute.
    """
    await updates.latest_version()
    await updates.latest_version()
    await updates.latest_version()

    assert len(FakeClient.calls) == 1


async def test_pressing_the_button_asks_again_anyway():
    """NEGATIVE CONTROL for the cache: `force` exists because somebody who has
    just updated wants the new number now, not in fifty minutes. A cache with no
    way past it would show them the old one and look broken.
    """
    await updates.latest_version()
    FakeClient.body = PYPROJECT.replace("2607.99.0", "2607.100.0")

    assert await updates.latest_version(force=True) == "2607.100.0"
    assert len(FakeClient.calls) == 2


async def test_a_failure_after_a_success_returns_the_answer_we_already_had():
    """A stale answer beats none. GitHub being briefly unreachable should not
    turn "an update is available" into "couldn't check" and back again on every
    poll — the banner would flicker for reasons that have nothing to do with the
    instance.
    """
    assert await updates.latest_version() == "2607.99.0"
    FakeClient.status_error = RuntimeError("502 from GitHub")

    assert await updates.latest_version(force=True) == "2607.99.0"


async def test_a_failure_does_not_wipe_what_was_cached():
    """NEGATIVE CONTROL for the above: the fallback must not be a one-shot.

    Clearing the cache on failure would return the stale answer once and then
    None for every subsequent check, which is the flicker the fallback exists to
    prevent — just delayed by one request.
    """
    await updates.latest_version()
    FakeClient.status_error = RuntimeError("still down")

    assert await updates.latest_version(force=True) == "2607.99.0"
    assert await updates.latest_version(force=True) == "2607.99.0"


async def test_a_bad_response_does_not_wedge_the_check_for_an_hour():
    """GitHub serving an error page is a 200 with HTML in it, which parses to
    nothing. A version check that answered None for a full hour afterwards would
    stay broken long after GitHub recovered.

    Two things prevent it independently — the `if version:` guard on the write,
    and the `cached is not None` guard on the read — and mutation-checking shows
    either one alone is sufficient. Removing *both* turns this red. The pin is on
    the recovery, not on which guard delivers it.
    """
    FakeClient.body = "<html><body>404 Not Found</body></html>"

    assert await updates.latest_version() is None

    FakeClient.body = PYPROJECT
    assert await updates.latest_version() == "2607.99.0"  # not stuck on the bad one


async def test_a_fork_can_check_its_own_repository():
    """Otherwise a fork reports itself permanently out of date against somebody
    else's release cadence, and the Update button offers to install a stranger's
    code.
    """
    import os

    os.environ["SIFT_UPDATE_REPO"] = "someone/their-fork"
    try:
        await updates.latest_version()
    finally:
        del os.environ["SIFT_UPDATE_REPO"]

    assert FakeClient.calls == [
        "https://raw.githubusercontent.com/someone/their-fork/main/pyproject.toml"
    ]


async def test_a_blank_override_falls_back_to_the_default_repo():
    """NEGATIVE CONTROL: an empty environment variable is how a deploy platform
    represents "unset". Taken literally it builds a URL with no repo in it.
    """
    import os

    os.environ["SIFT_UPDATE_REPO"] = "   "
    try:
        await updates.latest_version()
    finally:
        del os.environ["SIFT_UPDATE_REPO"]

    assert FakeClient.calls == [
        "https://raw.githubusercontent.com/holyscotsman/Sift/main/pyproject.toml"
    ]


async def test_never_checked_and_unreachable_is_none_not_a_guess():
    """The case the whole design turns on: with nothing cached and no network,
    the answer is "I don't know". `test_system.py` pins the endpoint's wording;
    this pins the value it is given.
    """
    FakeClient.status_error = RuntimeError("no network")

    assert await updates.latest_version() is None
