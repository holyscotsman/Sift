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


async def test_poster_cache_evicts_oldest_over_cap(settings, factory, tmp_path, monkeypatch):
    import os

    import httpx

    from sift.db.models import Movie
    from sift.services import posters as posters_mod
    from sift.services.posters import PosterCache

    settings.posters.cache_dir = tmp_path / "cache"
    with factory() as session:
        for i in (1, 2, 3):
            session.add(Movie(tmdb_id=i, title=f"M{i}", in_plex=True, poster_url="http://img/x"))
        session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 600)

    cache = PosterCache(settings, factory, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(posters_mod, "_MAX_CACHE_BYTES", 1500)  # fits two, not three

    assert await cache.get(1) is not None
    os.utime(cache.path_for(1), (1, 1))  # make 1 clearly the oldest
    assert await cache.get(2) is not None
    assert await cache.get(3) is not None  # pushes past the cap → evict oldest

    assert cache.cached(1) is None  # oldest evicted
    assert cache.cached(3) is not None  # the file just written always survives


async def test_dead_stored_poster_url_heals_via_tmdb(settings, factory, tmp_path):
    import httpx
    from pydantic import SecretStr

    from sift.db.models import Movie
    from sift.services.posters import PosterCache

    settings.posters.cache_dir = tmp_path / "cache"
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    with factory() as session:
        session.add(
            Movie(tmdb_id=603, title="The Matrix", in_plex=True,
                  poster_url="https://dead.example/poster.jpg")
        )
        session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dead.example":
            return httpx.Response(404)  # the stored URL is a corpse
        if request.url.path.endswith("/movie/603"):
            return httpx.Response(200, json={"poster_path": "/m.jpg"})
        if request.url.path.endswith("/m.jpg"):
            return httpx.Response(200, content=b"poster-bytes")
        return httpx.Response(404)

    cache = PosterCache(settings, factory, transport=httpx.MockTransport(handler))
    path = await cache.get(603)
    assert path is not None and path.read_bytes() == b"poster-bytes"
    # The stored corpse was healed to the TMDB URL for next time.
    with factory() as session:
        assert "image.tmdb.org" in session.get(Movie, 603).poster_url


def _seed_cache_dir(cache: PosterCache, count: int) -> None:
    """Pretend the cache already holds `count` posters from earlier sessions."""
    directory = cache.path_for(0).parent
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (directory / f"seed{i}.img").write_bytes(b"x" * 32)


async def _fetch_counting_stats(
    cache: PosterCache, tmdb_id: int, monkeypatch: pytest.MonkeyPatch
) -> int:
    """Number of `stat()` calls a single poster fetch makes."""
    from pathlib import Path as _Path

    real = _Path.stat
    calls = 0

    def counting(self: _Path, **kw: object) -> object:
        nonlocal calls
        calls += 1
        return real(self, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(_Path, "stat", counting)
    try:
        assert await cache.get(tmdb_id) is not None
    finally:
        monkeypatch.undo()
    return calls


async def test_caching_a_poster_costs_the_same_however_big_the_cache_is(
    settings, factory, tmp_path, monkeypatch
):
    """A first scroll through a large library fetches hundreds of posters, and
    every one of them used to stat the entire cache directory to answer "am I
    over the cap?" — a question that is almost always no. Fifteen thousand
    cached posters meant fifteen thousand syscalls per thumbnail.

    The property is not "fewer stats" but "the per-fetch cost does not grow with
    the cache", which is what makes a big library behave like a small one.
    """
    counts: dict[int, int] = {}
    for label, seeded in (("small", 10), ("large", 400)):
        settings.posters.cache_dir = tmp_path / label
        with factory() as session:
            for i in (1, 2):
                if session.get(Movie, i) is None:
                    session.add(
                        Movie(tmdb_id=i, title=f"M{i}", in_plex=True,
                              poster_url="https://image.tmdb.org/t/p/w342/s.jpg")
                    )
            session.commit()
        cache = PosterCache(settings, factory, transport=_transport())
        _seed_cache_dir(cache, seeded)
        await cache.get(1)  # first write of the process measures the directory once
        counts[seeded] = await _fetch_counting_stats(cache, 2, monkeypatch)

    # Forty times the cache, and the same handful of syscalls.
    assert counts[400] <= counts[10] + 2, counts


async def test_the_running_total_is_re_measured_after_an_eviction(
    settings, factory, tmp_path, monkeypatch
):
    """NEGATIVE CONTROL: a counter that drifts is worse than no counter.

    Eviction is the one moment the directory shrinks behind the count's back. If
    the running total is not reset to what is actually on disk afterwards, it
    stays permanently above the cap and every later fetch evicts something —
    turning the cache into a treadmill that throws away the poster it just read.
    """
    from sift.services import posters as posters_mod

    settings.posters.cache_dir = tmp_path / "cache"
    with factory() as session:
        for i in (1, 2, 3, 4):
            session.add(Movie(tmdb_id=i, title=f"M{i}", in_plex=True, poster_url="http://img/x"))
        session.commit()

    cache = PosterCache(
        settings,
        factory,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"x" * 600)),
    )
    monkeypatch.setattr(posters_mod, "_MAX_CACHE_BYTES", 1500)  # fits two, not three

    for i in (1, 2, 3):
        assert await cache.get(i) is not None
    assert cache.cached(1) is None  # the eviction happened

    # After it, the count must describe the directory as it now is.
    _count, on_disk = cache.stats()
    assert cache._bytes_on_disk == on_disk

    # And the next fetch must evict exactly one more, not everything.
    assert await cache.get(4) is not None
    assert cache.cached(4) is not None
    assert cache.stats()[0] == 2


async def test_a_canon_poster_needs_no_tmdb_lookup(settings, factory, tmp_path):
    """The Missing page is entirely titles you do not own.

    None of them has a `movies` row, so every thumbnail fell through to a live
    TMDB lookup — one network round trip per poster, on a page that shows thirty
    at once and can show five hundred. The path was in the database the whole
    time: the canon refresh stores `canon_movies.poster_path` for exactly these
    titles, and nothing read it. It could not even be cached back into `movies`
    afterwards, because there is no row to write it to — so the lookup repeated
    every time the image cache went cold, which on an ephemeral disk is every
    redeploy.
    """
    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")

    with factory() as session:
        # Canon only: no Movie row, which is the whole point.
        session.add(
            CanonMovie(tmdb_id=27205, title="Inception", year=2010, poster_path="/canon.jpg")
        )
        session.commit()

    lookups: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "api.themoviedb.org" in str(request.url):
            lookups.append(str(request.url))
            return httpx.Response(200, json={"poster_path": "/resolved.jpg"})
        return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})

    cache = PosterCache(settings, factory, transport=httpx.MockTransport(handler))
    path = await cache.get(27205)

    assert path is not None and path.read_bytes() == _JPEG
    assert not lookups, f"asked TMDB for a poster path it already had: {lookups}"


async def test_an_owned_poster_still_wins_over_the_canon_one(settings, factory, tmp_path):
    """NEGATIVE CONTROL: the library's own artwork is the better answer.

    A film you own may have a poster from Radarr or a healed TMDB URL, and the
    canon's copy is a fallback for titles that have no row of their own — not a
    replacement for one that does.
    """
    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")

    with factory() as session:
        session.add(
            Movie(
                tmdb_id=603,
                title="The Matrix",
                in_plex=True,
                poster_url="https://image.tmdb.org/t/p/w342/owned.jpg",
            )
        )
        session.add(CanonMovie(tmdb_id=603, title="The Matrix", poster_path="/canon.jpg"))
        session.commit()

    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})

    cache = PosterCache(settings, factory, transport=httpx.MockTransport(handler))
    assert await cache.get(603) is not None
    assert any("owned.jpg" in url for url in asked), f"fetched the wrong artwork: {asked}"


async def test_thirty_posters_do_not_queue_behind_each_other(settings, factory, tmp_path):
    """The Missing page asks for thirty thumbnails at once, and each one has to
    read the database to find out where the artwork lives.

    That read ran on the event loop. Against local SQLite it costs microseconds
    and is invisible; against a hosted database it is a network round trip, and
    while it is in flight *nothing else in the process moves* — including the
    page's own API call. Thirty of them in a row is how a page stops loading.

    What is asserted is *overlap*, not elapsed time. A wall-clock threshold would
    depend on how many worker threads the machine happens to give us and how
    loaded it is, which is how a test starts passing locally and failing in CI.
    Counting how many reads are in flight at once does not: on the event loop it
    can only ever be one.
    """
    import asyncio
    import threading
    import time

    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = False  # the DB read is the whole subject here

    with factory() as session:
        for n in range(30):
            session.add(CanonMovie(tmdb_id=9_000 + n, title=f"Canon {n}", poster_path="/p.jpg"))
        session.commit()

    lock = threading.Lock()
    in_flight = 0
    peak = 0

    class SlowFactory:
        """A database that answers, but not instantly — a hosted one, in other words."""

        kw = factory.kw

        def __call__(self):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.05)
            with lock:
                in_flight -= 1
            return factory()

    cache = PosterCache(settings, SlowFactory(), transport=_transport())
    await asyncio.gather(*(cache.get(9_000 + n) for n in range(30)))

    assert peak > 1, (
        "every database read waited for the one before it — the reads are running "
        "on the event loop, which blocks the whole server while each one is in flight"
    )


async def test_the_poster_still_comes_back(settings, factory, tmp_path):
    """NEGATIVE CONTROL: a fetch that returns nothing is extremely concurrent.

    Everything above is satisfied perfectly by a cache that stopped serving
    posters, so this pins that the bytes still arrive.
    """
    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = False

    with factory() as session:
        session.add(CanonMovie(tmdb_id=4242, title="Canon", poster_path="/p.jpg"))
        session.commit()

    cache = PosterCache(settings, factory, transport=_transport())
    path = await cache.get(4242)
    assert path is not None and path.read_bytes() == _JPEG


async def test_a_page_of_thumbnails_opens_one_connection_pool(settings, factory, tmp_path):
    """A client owns a connection pool, and one was being built per download.

    Thirty thumbnails meant thirty pools and thirty TLS handshakes to the image
    host, none of them reused. A shared client needs a handful of connections and
    keeps them warm — which matters most on exactly the page that fetches thirty
    at once.
    """
    import asyncio

    import httpx as _httpx

    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = False

    with factory() as session:
        for n in range(30):
            session.add(CanonMovie(tmdb_id=7_100 + n, title=f"C{n}", poster_path="/p.jpg"))
        session.commit()

    built = 0
    real_init = _httpx.AsyncClient.__init__

    def counting_init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        nonlocal built
        built += 1
        real_init(self, *args, **kwargs)

    cache = PosterCache(settings, factory, transport=_transport())
    _httpx.AsyncClient.__init__ = counting_init  # type: ignore[method-assign]
    try:
        await asyncio.gather(*(cache.get(7_100 + n) for n in range(30)))
    finally:
        _httpx.AsyncClient.__init__ = real_init  # type: ignore[method-assign]
        await cache.aclose()

    assert built == 1, f"{built} HTTP clients for thirty posters"


async def test_the_cache_still_works_after_it_is_closed(settings, factory, tmp_path):
    """NEGATIVE CONTROL: a shared client must not become a one-shot.

    Closing it on teardown is required — the pool would otherwise leak on every
    settings rebuild — but a cache that could never fetch again after a close
    would break the next scan instead.
    """
    from sift.db.models import CanonMovie

    settings.posters.cache_dir = tmp_path
    settings.tmdb.enabled = False

    with factory() as session:
        session.add(CanonMovie(tmdb_id=7_200, title="C", poster_path="/p.jpg"))
        session.add(CanonMovie(tmdb_id=7_201, title="D", poster_path="/p.jpg"))
        session.commit()

    cache = PosterCache(settings, factory, transport=_transport())
    assert await cache.get(7_200) is not None
    await cache.aclose()
    assert await cache.get(7_201) is not None
    await cache.aclose()
