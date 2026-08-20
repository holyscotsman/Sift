"""Extending the Missing list past the twenty-five thousand that ship with Sift.

Two sources feed it — TMDB discovery and whichever AI providers are connected —
and both write into the same table the built-in list uses, so the result is one
longer list rather than a second surface to reconcile.

The pins here are mostly about *restraint*: what the top-up refuses to do. It
must not spend API budget on a list nobody has reached the bottom of, must not
re-offer a film that is owned or already refused, must not take an AI's word for
anything, and must not admit a direct-to-video release however popular.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from sift.db.models import CanonEntry, IgnoredTitle, Movie, Setting
from sift.services import topup

from .conftest import mock_transport


def _result(tmdb_id: int, title: str, *, votes: int = 5_000, year: int = 1999):
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": f"{year}-01-01",
        "vote_average": 7.5,
        "vote_count": votes,
        "adult": False,
    }


def _handler(pages: dict[int, list[dict]]):
    """One page of discovery results per requested page, empty past the end."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json={"results": pages.get(page, [])})

    handle.seen = seen  # type: ignore[attr-defined]
    return handle


@pytest.fixture
def tmdb(settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    return settings


async def test_discovery_titles_join_the_same_list_the_built_in_canon_uses(factory, tmdb):
    """One table, one ranking, one set of subtractions. A top-up that wrote
    somewhere else would need its own paging, its own ignore handling and its own
    reconciliation with the canon — three chances to disagree with itself."""
    handler = _handler({1: [_result(603, "The Matrix")]})
    result = await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))

    assert result["added"] == 1 and result["ran"] is True
    with factory() as session:
        row = session.scalars(select(CanonEntry).where(CanonEntry.tmdb_id == 603)).one()
        assert row.title == "The Matrix"
        assert row.tier == topup.TOPUP_TIER
        # Already resolved: discovery hands back TMDB ids, so these never spend
        # the resolution budget the IMDb-keyed canon has to.
        assert row.review_status == "resolved"
        assert row.file_version == topup.FILE_VERSION


async def test_it_does_not_spend_api_budget_on_a_list_that_is_still_deep(factory, tmdb):
    """The low-water check. Adding to a queue nobody has reached the bottom of
    buys nothing and costs rate limit that the resolution budget needs."""
    with factory() as session:
        session.add_all(
            [
                CanonEntry(
                    imdb_id=f"tt{i:07d}",
                    title=f"Film {i}",
                    tier=1,
                    sources=[],
                    tmdb_id=i,
                    review_status="resolved",
                )
                for i in range(1, topup.LOW_WATER + 2)
            ]
        )
        session.commit()

    handler = _handler({1: [_result(603, "The Matrix")]})
    result = await topup.topup(factory, tmdb, transport=mock_transport(handler))

    assert result["ran"] is False and result["added"] == 0
    assert handler.seen == [], "discovery ran anyway"


async def test_NEGATIVE_CONTROL_a_short_list_does_run_without_being_forced(factory, tmdb):
    """NEGATIVE CONTROL: the low-water check must be a check, not an off switch.
    A guard that never lets anything through would pass the test above and make
    the whole feature dead code."""
    handler = _handler({1: [_result(603, "The Matrix")]})
    result = await topup.topup(factory, tmdb, transport=mock_transport(handler))

    assert result["ran"] is True and result["added"] == 1


async def test_owned_refused_and_already_listed_films_are_never_offered_again(factory, tmdb):
    """All three subtractions, at the point of writing rather than only at the
    point of reading. A film written into the list and filtered out on the way
    back is invisible but not free: it is a row, an id, and a title that shows up
    in every count."""
    with factory() as session:
        session.add(Movie(tmdb_id=1, title="Owned", in_plex=True))
        session.add(IgnoredTitle(tmdb_id=2, title="Refused"))
        session.add(
            CanonEntry(imdb_id="tt0000003", title="Already Listed", tier=1, sources=[], tmdb_id=3)
        )
        session.commit()

    handler = _handler(
        {
            1: [
                _result(1, "Owned"),
                _result(2, "Refused"),
                _result(3, "Already Listed"),
                _result(4, "Genuinely New"),
            ]
        }
    )
    result = await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))

    assert result["added"] == 1
    # Not merely unwritten — never *considered*. The three known films are dropped
    # at the gate, before anything is carried forward, because a candidate that
    # survives to the AI stage costs a TMDB search and a detail call each. There
    # is a second check at the write, since discovery and the write are minutes
    # apart on a slow API and a scan can land in between; this asserts the first
    # one is doing its job rather than being covered for by the second.
    assert result["considered"] == 1
    with factory() as session:
        added = session.scalars(
            select(CanonEntry).where(CanonEntry.file_version == topup.FILE_VERSION)
        ).all()
        assert [r.tmdb_id for r in added] == [4]


async def test_a_direct_to_video_release_is_refused_however_popular_it_is(factory, tmdb):
    """The exclusion list applies to discovery, not only to the built-in canon.
    TMDB's release-type filter does most of the work at the query; this is what
    catches the rest."""
    handler = _handler(
        {
            1: [
                _result(10, "The Lion King II: Simba's Pride", votes=80_000, year=1998),
                _result(11, "Battlefield Earth", votes=80_000, year=2000),
            ]
        }
    )
    result = await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))

    # Battlefield Earth had a theatrical release and was awful. It stays a
    # candidate: the rule is about distribution, never about quality.
    assert result["added"] == 1
    with factory() as session:
        titles = [
            r.title
            for r in session.scalars(
                select(CanonEntry).where(CanonEntry.file_version == topup.FILE_VERSION)
            )
        ]
        assert titles == ["Battlefield Earth"]


async def test_unreleased_and_barely_seen_titles_are_refused(factory, tmdb):
    """Two gates that have nothing to do with taste. A film that is not out yet is
    not missing from a library, and one with almost no votes is not a film anyone
    can be said to be missing."""
    handler = _handler(
        {
            1: [
                {**_result(20, "Next Year"), "release_date": "2099-01-01"},
                _result(21, "Seen By Nobody", votes=topup.MIN_VOTES - 1),
                _result(22, "Real Film"),
            ]
        }
    )
    result = await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))
    assert result["added"] == 1


async def test_the_theatrical_filter_is_applied_at_the_query(factory, tmdb):
    """Asked of TMDB rather than sorted out afterwards. The owner's rule — a
    theatrical release must be considered, a direct-to-video one must not — is
    exactly what `with_release_type=3|2` means, and asking for it costs nothing
    while filtering afterwards costs a page of results per page of candidates."""
    handler = _handler({1: [_result(603, "The Matrix")]})
    await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))

    params = handler.seen[0].url.params
    assert params.get("with_release_type") == "3|2"
    assert int(params.get("with_runtime.gte")) == topup.MIN_RUNTIME
    assert params.get("include_adult") in ("false", "False")


async def test_the_cursor_moves_so_the_next_run_reads_further_in(factory, tmdb):
    """Without this every run re-reads page one, finds the same films, discards
    all of them as known, and the list never gets any longer — a feature that
    burns rate limit and produces nothing, which looks exactly like a feature that
    has run out of things to find."""
    handler = _handler({p: [_result(600 + p, f"Film {p}")] for p in range(1, 12)})
    await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))

    with factory() as session:
        cursor = session.get(Setting, topup._CURSOR_KEY)
        assert cursor is not None
        assert cursor.value["popular"] == topup.PAGES_PER_RUN

    first_pages = [int(r.url.params["page"]) for r in handler.seen]
    handler.seen.clear()
    await topup.topup(factory, tmdb, force=True, transport=mock_transport(handler))
    second_pages = [int(r.url.params["page"]) for r in handler.seen]

    assert max(first_pages) < max(second_pages), "the second run re-read the first run's pages"


async def test_without_tmdb_it_says_so_rather_than_reporting_an_empty_list(factory, settings):
    """An empty result and "no connection" are different answers, and only one of
    them tells the owner what to do about it."""
    settings.tmdb.enabled = False
    result = await topup.topup(factory, settings, force=True)
    assert result["ran"] is False and result["note"] == "connect TMDB first"


# --------------------------------------------------------------- the AI source


class FakeProvider:
    """Stands in for a connected provider; returns a canned JSON list."""

    name = "fake"
    model = "fake"

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def complete(self, *, system: str, prompt: str):
        from sift.ai.provider import Completion

        return Completion(text=self._payload, provider="anthropic", model="m", latency_ms=1.0)

    async def health(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


_AI_PROPOSAL = """[
  {"title": "Stalker", "year": 1979, "reason": "Essential."},
  {"title": "Totally Made Up Film", "year": 2001, "reason": "Hallucinated."},
  {"title": "The Lion King II: Simba's Pride", "year": 1998, "reason": "A childhood favourite."}
]"""

_AI_DETAILS = {
    50: {
        "title": "Stalker",
        "vote_count": 9000,
        "vote_average": 8.2,
        "runtime": 162,
        "release_date": "1979-05-25",
        "adult": False,
    },
    52: {
        "title": "The Lion King II: Simba's Pride",
        "vote_count": 80_000,
        "vote_average": 7.0,
        "runtime": 81,
        "release_date": "1998-10-27",
        "adult": False,
    },
}
_AI_SEARCH = {"Stalker": 50, "The Lion King II: Simba's Pride": 52}


def _mixed_handler(discovery: list[dict]):
    """Discovery, search and detail on one transport, the way the real API is."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/discover/movie"):
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json={"results": discovery if page == 1 else []})
        if path.endswith("/search/movie"):
            tid = _AI_SEARCH.get(request.url.params.get("query", ""))
            return httpx.Response(200, json={"results": [{"id": tid}] if tid else []})
        if "/movie/" in path:
            detail = _AI_DETAILS.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=detail) if detail else httpx.Response(404)
        return httpx.Response(404)

    return handle


async def test_ai_proposals_join_the_list_only_after_they_survive_the_gates(
    factory, tmdb, monkeypatch
):
    """The third source, and the one that most needs watching. An AI names films;
    TMDB decides whether they exist and the deterministic gates decide whether
    they count. Nothing here takes a model's word for anything."""
    from sift.ai import musthave

    monkeypatch.setattr(musthave, "build_providers", lambda _s: (None, FakeProvider(_AI_PROPOSAL)))

    result = await topup.topup(
        factory, tmdb, force=True, transport=mock_transport(_mixed_handler([]))
    )

    assert result["added"] == 1
    with factory() as session:
        rows = session.scalars(
            select(CanonEntry).where(CanonEntry.file_version == topup.FILE_VERSION)
        ).all()
        # Stalker is real and survives. The hallucinated film dies at the search —
        # a title TMDB has never heard of cannot be added by asserting it exists.
        # The direct-to-video sequel dies at the exclusion list, which is the one
        # gate aimed squarely at what an AI is most likely to get wrong.
        assert [r.title for r in rows] == ["Stalker"]
        assert rows[0].sources == ["suggested"]


async def test_two_sources_naming_the_same_film_keep_both_reasons(factory, tmdb, monkeypatch):
    """The one case where counting sources means anything. Both reasons are kept
    because agreement between independent sources is real evidence — which is
    exactly what the built-in list, where 24,417 of 25,000 entries carry a single
    source, cannot provide on its own."""
    from sift.ai import musthave

    monkeypatch.setattr(
        musthave,
        "build_providers",
        lambda _s: (None, FakeProvider('[{"title": "Stalker", "year": 1979, "reason": "x"}]')),
    )

    result = await topup.topup(
        factory,
        tmdb,
        force=True,
        transport=mock_transport(_mixed_handler([_result(50, "Stalker", year=1979)])),
    )

    assert result["added"] == 1
    with factory() as session:
        row = session.scalars(select(CanonEntry).where(CanonEntry.tmdb_id == 50)).one()
        assert "suggested" in row.sources and len(row.sources) > 1


async def test_NEGATIVE_CONTROL_no_ai_connected_is_not_an_error(factory, tmdb, monkeypatch):
    """NEGATIVE CONTROL: the whole arrangement exists so that the list works with
    or without AI. Discovery must still fill it, and the run must still report
    success."""
    from sift.ai import musthave

    monkeypatch.setattr(musthave, "build_providers", lambda _s: (None, None))

    result = await topup.topup(
        factory,
        tmdb,
        force=True,
        transport=mock_transport(_mixed_handler([_result(603, "The Matrix")])),
    )

    assert result["ran"] is True and result["added"] == 1


# ------------------------------------------------------------------ the scan phase


async def test_the_scan_tops_up_only_when_the_list_is_low(factory, tmdb):
    """The low-water check exists so this can run on every scan without spending
    API budget on a queue nobody has reached the bottom of. Until the scan called
    it, that check had no caller at all — the docstring described a code path
    nothing exercised."""
    from sift.ingest.pipeline import ScanPipeline

    calls: list[bool] = []

    async def fake_topup(_factory, _settings, *, force=False, **_kw):
        calls.append(force)
        return {"added": 3, "remaining": 12, "ran": True}

    pipe = ScanPipeline(factory, tmdb)
    import sift.services.topup as topup_module

    original = topup_module.topup
    topup_module.topup = fake_topup
    try:
        counts = await pipe._phase_topup()
    finally:
        topup_module.topup = original

    # force=False, so the service's own low-water check decides. A phase that
    # forced it would sweep TMDB on every single scan.
    assert calls == [False]
    assert counts == {"topup_added": 3}


async def test_a_skipped_top_up_is_reported_rather_than_left_as_a_silent_zero(factory, tmdb):
    """ "Added 0" and "did not look" are different answers, and only one of them
    means something is wrong."""
    from sift.ingest.pipeline import ScanPipeline

    async def fake_topup(_factory, _settings, *, force=False, **_kw):
        return {"added": 0, "remaining": 20_000, "ran": False, "note": "the list is still deep"}

    pipe = ScanPipeline(factory, tmdb)
    import sift.services.topup as topup_module

    original = topup_module.topup
    topup_module.topup = fake_topup
    try:
        assert await pipe._phase_topup() == {"topup_skipped": 1}
    finally:
        topup_module.topup = original


async def test_NEGATIVE_CONTROL_a_broken_top_up_does_not_fail_the_scan(factory, tmdb):
    """NEGATIVE CONTROL: a discovery sweep is a convenience. A dead TMDB, a
    rate limit or a bug in the sweep must never be the reason a scan that read the
    whole library reports failure."""
    from sift.ingest.pipeline import ScanPipeline

    async def boom(_factory, _settings, *, force=False, **_kw):
        raise RuntimeError("TMDB fell over")

    pipe = ScanPipeline(factory, tmdb)
    import sift.services.topup as topup_module

    original = topup_module.topup
    topup_module.topup = boom
    try:
        assert await pipe._phase_topup() == {"topup_failed": 1}
    finally:
        topup_module.topup = original
