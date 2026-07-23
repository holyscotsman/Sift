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
