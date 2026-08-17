"""Taste recommendations — anchor selection, TMDB aggregation, and guard rails."""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from sift.analysis import recommend
from sift.db.models import Movie, Rating, RatingSource


def _seed(factory, tmdb_id: int, title: str, rating: float, votes: int = 1000) -> None:
    with factory() as session:
        m = Movie(tmdb_id=tmdb_id, title=title, in_plex=True)
        m.ratings.append(Rating(source=RatingSource.TMDB, value=rating, votes=votes))
        session.add(m)
        session.commit()


async def test_disabled_tmdb_returns_connect_note(factory, settings):
    settings.tmdb.enabled = False
    result = await recommend.recommendations(factory, settings)
    assert result["items"] == []
    assert "TMDB" in result["note"]


async def test_no_library_returns_scan_note(factory, settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    result = await recommend.recommendations(factory, settings)
    assert result["items"] == []
    assert "scan" in result["note"].lower()


async def test_ranks_and_excludes_owned(factory, settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    _seed(factory, 603, "The Matrix", rating=8.7)
    _seed(factory, 27205, "Inception", rating=8.3)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recommendations"):
            # Both anchors surface 605; only Matrix surfaces 604 (already owned → excluded);
            # 27205 (an owned anchor) also shows up and must be filtered out.
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 605, "title": "The Matrix Reloaded", "release_date": "2003-05-15",
                         "vote_average": 7.0, "poster_path": "/x.jpg"},
                        {"id": 27205, "title": "Inception", "release_date": "2010-07-16",
                         "vote_average": 8.3, "poster_path": "/y.jpg"},
                    ]
                },
            )
        return httpx.Response(200, json={"results": []})

    result = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    ids = [i["tmdb_id"] for i in result["items"]]
    assert 605 in ids  # surfaced by both anchors
    assert 603 not in ids and 27205 not in ids  # owned titles never recommended
    top = result["items"][0]
    assert top["tmdb_id"] == 605
    assert top["reason"].startswith("Because you own")
    assert top["year"] == 2003


async def test_all_anchor_calls_failing_reads_as_connection_error(factory, settings):
    # A bad key / TMDB outage must not masquerade as "your library covers the graph".
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    _seed(factory, 603, "The Matrix", rating=8.7)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)  # bad/expired key — non-retriable, every call fails

    result = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    assert result["items"] == []
    assert "TMDB" in result["note"] and "covers" not in result["note"]


async def test_falls_back_to_similar_when_recommendations_empty(factory, settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    _seed(factory, 603, "The Matrix", rating=8.7)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recommendations"):
            return httpx.Response(200, json={"results": []})
        if request.url.path.endswith("/similar"):
            return httpx.Response(
                200,
                json={"results": [{"id": 605, "title": "The Matrix Reloaded",
                                   "release_date": "2003-01-01", "vote_average": 7.0}]},
            )
        return httpx.Response(404)

    result = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    assert [i["tmdb_id"] for i in result["items"]] == [605]


async def test_taste_weights_reorder_but_never_gate(factory, settings):
    # Two candidates: X leads on raw anchor relevance; Y matches the library's
    # dominant genre + era. Sliders at zero → raw order (X first). Genre/era
    # sliders up → Y overtakes. Both always present — weights reorder, never gate.
    from sift.analysis import profile

    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    with factory() as session:
        m = Movie(tmdb_id=603, title="Anchor Comedy", in_plex=True,
                  year=1994, genres=["Comedy"])
        m.ratings.append(Rating(source=RatingSource.TMDB, value=8.7, votes=1000))
        session.add(m)
        session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recommendations"):
            return httpx.Response(200, json={"results": [
                {"id": 111, "title": "X Drama", "release_date": "2010-01-01",
                 "vote_average": 7.0, "genre_ids": [18]},
                {"id": 222, "title": "Y Comedy", "release_date": "1994-06-01",
                 "vote_average": 7.0, "genre_ids": [35]},
            ]})
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)

    with factory() as session:
        profile.set_weights(session, {"genre": 0.0, "era": 0.0})
    zero = await recommend.recommendations(factory, settings, transport=transport)
    assert [i["tmdb_id"] for i in zero["items"]] == [111, 222]

    with factory() as session:
        profile.set_weights(session, {"genre": 1.0, "era": 1.0})
    weighted = await recommend.recommendations(factory, settings, transport=transport)
    assert [i["tmdb_id"] for i in weighted["items"]] == [222, 111]


async def test_most_recommended_leads_the_ranking(factory, settings):
    """"Recommended most" is a count of independent recommendations.

    The old key was anchor-strength × TMDB position, so one highly-rated film's
    top pick could outrank a title several different films in the library all
    surfaced. The fixture is built so the two keys genuinely *disagree*: the lone
    pick wins on weighted score (1.0 against 0.39) and loses on count (1 against
    3). Without that opposition the test passes under either ranking and pins
    nothing — which is what the first version of it did.
    """
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    _seed(factory, 1, "Masterpiece", rating=10.0, votes=500_000)
    for i, name in enumerate(("Weak One", "Weak Two", "Weak Three"), start=2):
        _seed(factory, i, name, rating=3.0, votes=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/recommendations"):
            return httpx.Response(200, json={"results": []})
        anchor = int(request.url.path.split("/")[-2])
        if anchor == 1:
            # Full-strength anchor, its pick first: contribution 1.0.
            return httpx.Response(200, json={"results": [{"id": 900, "title": "Lone Pick"}]})
        # Weak anchors, agreeing on 901 but only after nineteen others, so each
        # contributes 0.3 × 0.43 ≈ 0.13 — 0.39 between the three of them.
        results = [{"id": 20_000 + anchor * 100 + n, "title": f"F{n}"} for n in range(19)]
        results.append({"id": 901, "title": "Broad Agreement"})
        return httpx.Response(200, json={"results": results})

    result = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    ids = [i["tmdb_id"] for i in result["items"]]
    assert ids[0] == 901, "three films agreeing must outrank one strong film's top pick"
    assert 900 in ids


async def test_a_single_strong_anchor_still_beats_nothing(factory, settings):
    """NEGATIVE CONTROL: overlap leads, but it must not erase the weighted score.

    Ranking on count alone would leave every one-anchor title in arbitrary order.
    The weighted score still separates them, and tmdb_id breaks the last tie so
    the same library produces the same list every time.
    """
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    _seed(factory, 1, "Masterpiece", rating=9.6, votes=500_000)
    _seed(factory, 2, "Modest", rating=6.2, votes=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        anchor = int(request.url.path.split("/")[-2])
        if not request.url.path.endswith("/recommendations"):
            return httpx.Response(200, json={"results": []})
        rid = 800 if anchor == 1 else 801
        return httpx.Response(200, json={"results": [{"id": rid, "title": f"F{rid}"}]})

    first = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    second = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler)
    )
    ids = [i["tmdb_id"] for i in first["items"]]
    assert ids[0] == 800, "the stronger anchor's pick leads among equal overlap"
    assert ids == [i["tmdb_id"] for i in second["items"]], "the order must be stable"


async def test_the_pool_is_wide_enough_to_be_worth_browsing(factory, settings):
    """The cap that made this feature look broken.

    Twelve anchors reading twenty results each is 240 raw candidates *before*
    de-duplication and before removing what you already own — and anchors overlap
    heavily, so the distinct pool fell far short of a couple of hundred. The
    endpoint then returned twenty-four of them.
    """
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    for i in range(1, 81):
        _seed(factory, i, f"Owned {i}", rating=8.0, votes=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/recommendations"):
            return httpx.Response(200, json={"results": []})
        anchor = int(request.url.path.split("/")[-2])
        # Each anchor surfaces twenty candidates of its own, plus one shared.
        # Overlapping windows, because real anchors overlap heavily — give each
        # one twenty candidates nobody else surfaces and de-duplication never
        # bites, so any anchor count passes and the test pins nothing.
        # Stride 4 over a 20-wide window: twelve anchors yield ~64 distinct
        # titles, sixty yield ~256.
        results = [{"id": 99_999, "title": "Everyone agrees"}]
        results += [{"id": 10_000 + anchor * 4 + n, "title": f"C{n}"} for n in range(19)]
        return httpx.Response(200, json={"results": results})

    result = await recommend.recommendations(
        factory, settings, transport=httpx.MockTransport(handler), limit=500
    )
    assert len(result["items"]) >= 200, f"only {len(result['items'])} candidates"
    assert result["items"][0]["tmdb_id"] == 99_999, "the universally surfaced title leads"


def test_stored_recommendations_survive_a_page_load(factory):
    """They are computed once per scan and read back, not recomputed per visit."""
    from sift.analysis.recommend import Candidate, Taste, _store, rank, stored

    taste = Taste(top_genres=frozenset(), top_eras=frozenset(), genre_weight=0.5, era_weight=0.5)
    candidates = [
        Candidate(
            tmdb_id=500 + i, title=f"Film {i}", year=2000 + i, vote_average=7.0, poster_path=None
        )
        for i in range(5)
    ]
    for i, c in enumerate(candidates):
        c.sources = [(f"Anchor {n}", 1.0) for n in range(i + 1)]
        c.score = float(i)

    with factory() as session:
        written = _store(session, rank(candidates, taste), taste)
        assert written == 5
        items, total = stored(session, limit=3)

    assert total == 5
    assert len(items) == 3
    # Most-recommended first, and the stored order is the computed order.
    assert items[0]["tmdb_id"] == 504
    assert "Because you own" in items[0]["reason"]


def test_storing_replaces_rather_than_accumulates(factory):
    """NEGATIVE CONTROL: a title you have since acquired must leave the list.

    Merging instead of replacing would let a film you now own linger for ever,
    because nothing would think to remove it.
    """
    from sift.analysis.recommend import Candidate, Taste, _store, stored

    taste = Taste(top_genres=frozenset(), top_eras=frozenset(), genre_weight=0.5, era_weight=0.5)
    with factory() as session:
        old = Candidate(tmdb_id=1, title="Old", year=1999, vote_average=7.0, poster_path=None)
        new = Candidate(tmdb_id=2, title="New", year=2001, vote_average=7.0, poster_path=None)
        _store(session, [old], taste)
        _store(session, [new], taste)
        items, total = stored(session)

    assert total == 1
    assert [i["tmdb_id"] for i in items] == [2]
