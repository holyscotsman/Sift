"""Show suggestions — short by design, and seeded by what you finished.

The two decisions worth pinning: the list stays small, and a show you acquired
and never started never seeds it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.analysis import tv_recommend
from sift.db.models import Show
from sift.main import create_app


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _show(factory, tvdb_id, tmdb_id, title, *, plays=0, completion=None):
    with factory() as session:
        session.add(
            Show(
                tvdb_id=tvdb_id,
                tmdb_id=tmdb_id,
                title=title,
                plays=plays,
                mean_completion=completion,
                in_plex=True,
            )
        )
        session.commit()


def _candidate(tmdb_id, name, *, votes=1000, rating=8.0):
    return {
        "id": tmdb_id,
        "name": name,
        "vote_count": votes,
        "vote_average": rating,
        "first_air_date": "2019-04-01",
        "overview": "",
    }


# ---------------------------------------------------------------------- anchors


def test_only_shows_you_watched_through_are_seeds(factory):
    """A TV library is full of series acquired and never started. Seeding from
    those sends the whole list somewhere you already declined to go."""
    _show(factory, 1, 100, "Finished", plays=20, completion=0.95)
    _show(factory, 2, 200, "Sampled", plays=2, completion=0.1)
    _show(factory, 3, 300, "Never started", plays=0)
    with factory() as session:
        seeds, owned = tv_recommend.anchors(session)
    assert [a.title for a in seeds] == ["Finished"]
    # Everything you hold is still excluded from results, seed or not.
    assert owned == {100, 200, 300}


def test_watching_more_completely_counts_for_more(factory):
    _show(factory, 1, 100, "Devoured", plays=20, completion=1.0)
    _show(factory, 2, 200, "Got through it", plays=20, completion=0.6)
    with factory() as session:
        seeds, _ = tv_recommend.anchors(session)
    assert seeds[0].title == "Devoured"
    assert seeds[0].weight > seeds[1].weight


# ------------------------------------------------------------------------ rank


def test_the_list_stays_short():
    """Twenty-four film suggestions is a browse; twenty-four show suggestions is
    a second job."""
    candidates = {
        i: (_candidate(i, f"Show {i}"), ["Finished"], 1.0) for i in range(1, 40)
    }
    assert len(tv_recommend.rank(candidates, owned=set())) == tv_recommend.DEFAULT_LIMIT
    assert tv_recommend.DEFAULT_LIMIT <= 10


def test_agreement_across_your_shows_beats_a_better_rating():
    """Three series you finished pointing at the same show says more than one
    series pointing at something better reviewed."""
    candidates = {
        1: (_candidate(1, "Agreed on", rating=7.0), ["A", "B", "C"], 3.0),
        2: (_candidate(2, "Better reviewed", rating=9.5), ["A"], 1.0),
    }
    assert [s.title for s in tv_recommend.rank(candidates, owned=set())] == [
        "Agreed on",
        "Better reviewed",
    ]


def test_what_you_already_have_is_never_suggested():
    """NEGATIVE CONTROL."""
    candidates = {1: (_candidate(1, "Owned"), ["A"], 1.0)}
    assert tv_recommend.rank(candidates, owned={1}) == []


def test_a_show_nobody_has_rated_is_not_suggested():
    """NEGATIVE CONTROL: too few votes is unverifiable rather than an
    undiscovered gem, and one bad suggestion in a list of eight is a quarter of
    the screen."""
    candidates = {1: (_candidate(1, "Unknown", votes=3), ["A"], 5.0)}
    assert tv_recommend.rank(candidates, owned=set()) == []


# ------------------------------------------------------------------- the route


def test_with_no_tmdb_the_screen_says_why(client):
    """NEGATIVE CONTROL: an empty panel reads as a failure. An optional service
    being absent must be stated, not implied."""
    c, factory = client
    _show(factory, 1, 100, "Finished", plays=20, completion=0.95)
    body = c.get("/api/shows/suggestions").json()
    assert body["items"] == []
    assert "TMDB" in body["detail"]


def test_with_no_watch_history_the_screen_says_that_instead(client, settings):
    c, factory = client
    _show(factory, 1, 100, "Never started", plays=0)
    body = c.get("/api/shows/suggestions").json()
    assert body["items"] == []
    assert body["detail"]
