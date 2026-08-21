"""The async half of the TV recommender: fetching, merging and surviving.

`rank` and `anchors` have their own tests. `suggest` — the part that actually
talks to TMDB, once per seed, twice per seed — had none, and it carries two
properties the pure functions cannot express.

The first is stated in a comment and is the reason the try/except is there at all:
**one dead seed must not kill the list**. A seed whose TMDB lookup fails should
cost its own contribution and nothing else; a library with six watched shows
should not lose all six suggestions because one of them 404s.

The second is the merge. A show recommended by two different seeds is a stronger
suggestion than one recommended by either alone, and it should say so — both
titles in its reasons, and the weights added rather than replaced.
"""

from __future__ import annotations

from typing import Any

import pytest

from sift.analysis import tv_recommend
from sift.config import TmdbConfig
from sift.db.session import init_db, make_engine, make_session_factory


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(tmp_path / "tv.db")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture
def tmdb_on(settings):
    settings.tmdb = TmdbConfig(enabled=True, api_key="k")
    return settings


class FakeTmdb:
    """Stands in for TmdbClient. Records what it was asked and can fail on cue."""

    def __init__(self, by_id: dict[int, list[dict[str, Any]]], dead: set[int] | None = None):
        self._by_id = by_id
        self._dead = dead or set()
        self.asked: list[int] = []
        self.closed = False

    async def get_tv_recommendations(self, tmdb_id: int) -> list[dict[str, Any]]:
        self.asked.append(tmdb_id)
        if tmdb_id in self._dead:
            raise RuntimeError("TMDB said no")
        return self._by_id.get(tmdb_id, [])

    async def get_similar_tv(self, tmdb_id: int) -> list[dict[str, Any]]:
        return []

    async def aclose(self) -> None:
        self.closed = True


def _seed(monkeypatch, fake: FakeTmdb, anchors: list[tv_recommend.Anchor], owned: set[int]):
    monkeypatch.setattr("sift.clients.tmdb.TmdbClient", lambda *a, **k: fake)
    monkeypatch.setattr(tv_recommend, "anchors", lambda session: (anchors, owned))


def show(tmdb_id: int, name: str) -> dict[str, Any]:
    return {
        "id": tmdb_id,
        "name": name,
        "vote_average": 8.0,
        "vote_count": 900,
        "first_air_date": "2015-01-01",
    }


async def test_a_dead_seed_costs_only_its_own_suggestions(factory, tmdb_on, monkeypatch):
    """Six watched shows must not yield nothing because one of them 404s."""
    good = tv_recommend.Anchor(tvdb_id=1, tmdb_id=100, title="The Wire", weight=1.0)
    dead = tv_recommend.Anchor(tvdb_id=2, tmdb_id=200, title="Deadwood", weight=1.0)
    fake = FakeTmdb({100: [show(900, "Treme")]}, dead={200})
    _seed(monkeypatch, fake, [dead, good], owned=set())

    out = await tv_recommend.suggest(factory, tmdb_on, limit=10)

    assert [s.title for s in out] == ["Treme"]
    assert 200 in fake.asked, "the dead seed was asked, and its failure absorbed"
    assert fake.closed, "the client is closed even when a seed fails"


async def test_two_seeds_recommending_the_same_show_say_so(factory, tmdb_on, monkeypatch):
    """A show both of your favourites point at is a better suggestion than one
    either points at alone, and the card should name both."""
    a = tv_recommend.Anchor(tvdb_id=1, tmdb_id=100, title="The Wire", weight=1.0)
    b = tv_recommend.Anchor(tvdb_id=2, tmdb_id=200, title="Deadwood", weight=1.0)
    fake = FakeTmdb({100: [show(900, "Treme")], 200: [show(900, "Treme")]})
    _seed(monkeypatch, fake, [a, b], owned=set())

    out = await tv_recommend.suggest(factory, tmdb_on, limit=10)

    assert len(out) == 1
    assert set(out[0].because_of) == {"The Wire", "Deadwood"}


async def test_a_show_two_seeds_agree_on_outranks_one_only_a_single_seed_names(
    factory, tmdb_on, monkeypatch
):
    """The weights *add*, and the only way to see that is to make them compete.

    Asserting the reasons alone leaves the accumulation untested — a mutation
    that replaces the running weight with the latest anchor's passes, because
    with one candidate there is no ordering to get wrong. Two candidates, one
    named twice, and the ranking has to put it first.
    """
    a = tv_recommend.Anchor(tvdb_id=1, tmdb_id=100, title="The Wire", weight=1.0)
    b = tv_recommend.Anchor(tvdb_id=2, tmdb_id=200, title="Deadwood", weight=1.0)
    both = show(900, "Agreed On")
    one = show(901, "Named Once")
    # The singly-named show is *better* on its own merits, so only the added
    # weight can put the doubly-named one ahead of it.
    one["vote_average"] = 9.5
    one["vote_count"] = 50_000
    fake = FakeTmdb({100: [both, one], 200: [both]})
    _seed(monkeypatch, fake, [a, b], owned=set())

    out = await tv_recommend.suggest(factory, tmdb_on, limit=10)

    assert [s.title for s in out][0] == "Agreed On"


async def test_NEGATIVE_CONTROL_a_show_you_already_have_is_not_suggested(
    factory, tmdb_on, monkeypatch
):
    a = tv_recommend.Anchor(tvdb_id=1, tmdb_id=100, title="The Wire", weight=1.0)
    fake = FakeTmdb({100: [show(900, "Treme"), show(901, "Generation Kill")]})
    _seed(monkeypatch, fake, [a], owned={900})

    out = await tv_recommend.suggest(factory, tmdb_on, limit=10)

    assert [s.title for s in out] == ["Generation Kill"]


async def test_no_tmdb_key_means_no_suggestions_rather_than_an_error(factory, settings):
    """Every AI-and-API surface here degrades to quiet rather than to a failure."""
    settings.tmdb = TmdbConfig(enabled=False)
    assert await tv_recommend.suggest(factory, settings, limit=10) == []


async def test_nothing_watched_means_nothing_to_recommend_from(factory, tmdb_on, monkeypatch):
    """The seeds are shows you *finished*, not shows you own. A fresh library has
    none, and the honest answer is an empty list rather than a guess."""
    fake = FakeTmdb({})
    _seed(monkeypatch, fake, [], owned=set())

    assert await tv_recommend.suggest(factory, tmdb_on, limit=10) == []
    # Nothing was asked of TMDB either, which is the part worth having: the
    # early return is an optimisation rather than the guard — deleting it leaves
    # this green, because an empty seed list means the loop body never runs.
    # Checked by mutation, and recorded rather than dressed up.
    assert fake.asked == []
