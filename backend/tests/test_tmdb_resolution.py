"""How a canon entry becomes a TMDB id.

Ten thousand canon entries resolve through these two calls, and the answer
decides which film ends up on the Missing page. A wrong id there is not a blank
row — it is a *different film*, recommended confidently, and the owner has no way
to tell from the screen that the lookup was the thing that went wrong.

The client's auth and headers are covered in `test_clients.py`. This is about what
it does with the answers.
"""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from sift.clients.tmdb import TmdbClient
from sift.config import TmdbConfig


async def _noop_sleep(_seconds: float) -> None:
    return None


def _client(handler):
    return TmdbClient(
        TmdbConfig(api_key=SecretStr("tk")),
        base_url="http://tmdb.test",
        transport=httpx.MockTransport(handler),
        sleep=_noop_sleep,
    )


def _json(payload, path_check=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if path_check:
            path_check(request)
        return httpx.Response(200, json=payload)

    return handler


# ------------------------------------------------------------- find by imdb id


async def test_an_imdb_id_resolves_through_the_find_endpoint():
    """Exact, where a search is a guess. The canon arrives keyed by IMDb id and
    the overwhelming majority carry one; matching those by title and year instead
    would mean choosing between remakes and re-releases ten thousand times.
    """
    seen: dict[str, object] = {}

    def check(request: httpx.Request) -> None:
        seen["path"] = request.url.path
        seen["source"] = request.url.params.get("external_source")

    client = _client(_json({"movie_results": [{"id": 603, "title": "The Matrix"}]}, check))
    assert await client.find_by_imdb("tt0133093") == 603
    await client.aclose()

    assert seen["path"] == "/find/tt0133093"
    # Without this TMDB has no idea what kind of id it was handed.
    assert seen["source"] == "imdb_id"


async def test_an_imdb_id_tmdb_does_not_know_resolves_to_nothing():
    """NEGATIVE CONTROL: an empty `movie_results` is a real answer, not an error.

    The canon carries films TMDB has never indexed. Those must come back as "not
    resolved" so the entry stays pending and is retried — an exception here would
    abort the resolution phase mid-list.
    """
    client = _client(_json({"movie_results": []}))
    assert await client.find_by_imdb("tt9999999") is None
    await client.aclose()


async def test_a_person_or_show_match_is_not_taken_as_a_film():
    """`/find` returns `person_results`, `tv_results` and more alongside. Reading
    the wrong bucket would resolve a director's IMDb id to their *person* id and
    file it as a film — an id that looks perfectly valid and points at nothing.
    """
    client = _client(
        _json({
            "movie_results": [],
            "person_results": [{"id": 6384, "name": "Keanu Reeves"}],
            "tv_results": [{"id": 1399, "name": "Game of Thrones"}],
        })
    )
    assert await client.find_by_imdb("nm0000206") is None
    await client.aclose()


async def test_a_malformed_find_response_resolves_to_nothing():
    """A proxy, a login page or an error body all arrive as valid JSON of the
    wrong shape. Ten thousand entries run through this; one crash is the whole
    phase.
    """
    for payload in ([], {"movie_results": "not-a-list"}, {"movie_results": [{"title": "no id"}]}):
        client = _client(_json(payload))
        assert await client.find_by_imdb("tt0133093") is None
        await client.aclose()


# --------------------------------------------------------------- search by title


async def test_a_title_and_year_are_both_sent_when_the_year_is_known():
    """The year is what separates a remake from the original. Sending only the
    title makes the 2010 True Grit and the 1969 one the same question.
    """
    seen: dict[str, object] = {}

    def check(request: httpx.Request) -> None:
        seen["query"] = request.url.params.get("query")
        seen["year"] = request.url.params.get("year")

    client = _client(_json({"results": [{"id": 44264}]}, check))
    assert await client.search_movie("True Grit", 2010) == 44264
    await client.aclose()

    assert seen["query"] == "True Grit"
    assert seen["year"] == "2010"


async def test_no_year_is_omitted_rather_than_sent_empty():
    """NEGATIVE CONTROL: some canon entries have no year at all.

    `year=` or `year=None` in the query string is not the same as leaving it out —
    TMDB filters on it, and an empty filter returns nothing for a film that does
    exist.
    """
    seen: dict[str, object] = {}

    def check(request: httpx.Request) -> None:
        seen["params"] = dict(request.url.params)

    client = _client(_json({"results": [{"id": 603}]}, check))
    assert await client.search_movie("The Matrix") == 603
    await client.aclose()

    assert "year" not in seen["params"]


async def test_a_search_that_finds_nothing_resolves_to_nothing():
    """The ordinary outcome for an obscure title, and it has to stay
    distinguishable from a match — the entry is counted as an attempt and tried
    again, rather than being marked unresolvable on the strength of one miss.
    """
    client = _client(_json({"results": []}))
    assert await client.search_movie("A Film That Does Not Exist", 1971) is None
    await client.aclose()


async def test_the_first_result_is_the_one_taken():
    """TMDB orders by relevance, so the first is its own best answer. Taking any
    other would be second-guessing the only ranking available here.
    """
    client = _client(
        _json({"results": [{"id": 603, "title": "The Matrix"},
                           {"id": 605, "title": "The Matrix Revolutions"}]})
    )
    assert await client.search_movie("The Matrix", 1999) == 603
    await client.aclose()


async def test_a_malformed_search_response_resolves_to_nothing():
    for payload in ([], {"results": None}, {"results": [{"title": "no id"}]}, {"results": [None]}):
        client = _client(_json(payload))
        assert await client.search_movie("Anything") is None
        await client.aclose()
