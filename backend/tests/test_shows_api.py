"""The TV library listing.

Shows are deliberately never scored for removal — this list says what you have
and what it costs, and stops there.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import Episode, MediaFile, Season, Show
from sift.main import create_app

GB = 1_000_000_000
MIN_MS = 60_000


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _show(
    factory,
    tvdb_id,
    title,
    *,
    section="TV",
    seasons=1,
    episodes=10,
    size=2 * GB,
    res="1080p",
):
    with factory() as session:
        session.add(
            Show(tvdb_id=tvdb_id, title=title, library_section=section, in_plex=True, year=2001)
        )
        for s in range(1, seasons + 1):
            season = Season(show_id=tvdb_id, season_number=s, air_year=2000 + s)
            session.add(season)
            session.flush()
            for n in range(1, episodes + 1):
                episode = Episode(season_id=season.id, episode_number=n, has_file=True)
                session.add(episode)
                session.flush()
                session.add(
                    MediaFile(
                        episode_id=episode.id,
                        path=f"/tv/{tvdb_id}/s{s}e{n}.mkv",
                        part_group=f"{tvdb_id}-{s}-{n}",
                        size=size,
                        duration_ms=45 * MIN_MS,
                        resolution=res,
                        video_codec="h264",
                        source="plex",
                    )
                )
        session.commit()


def test_shows_are_listed_with_their_real_size(client):
    """Summed from the files, not from what Sonarr believes it imported."""
    c, factory = client
    _show(factory, 1, "Scrubs", seasons=2, episodes=10, size=2 * GB)
    body = c.get("/api/shows").json()
    assert body["total"] == 1
    show = body["items"][0]
    assert show["title"] == "Scrubs"
    assert show["season_count"] == 2
    assert show["episode_count"] == 20
    assert show["total_size"] == 40 * GB
    assert show["resolution"] == "1080p"


def test_every_show_library_appears_not_just_one_called_tv(client):
    """Cartoons, Anime and Game Shows are show libraries and belong here."""
    c, factory = client
    for i, section in enumerate(["TV", "Anime", "Cartoons", "Game Shows"], start=1):
        _show(factory, i, f"Series {i}", section=section, episodes=2)
    sections = c.get("/api/shows/sections").json()
    assert sections == ["Anime", "Cartoons", "Game Shows", "TV"]
    assert c.get("/api/shows").json()["total"] == 4


def test_shows_can_be_filtered_and_searched(client):
    c, factory = client
    _show(factory, 1, "Scrubs", section="TV", episodes=2)
    _show(factory, 2, "Frieren", section="Anime", episodes=2)
    assert c.get("/api/shows?section=Anime").json()["items"][0]["title"] == "Frieren"
    assert c.get("/api/shows?q=scru").json()["items"][0]["title"] == "Scrubs"


def test_a_show_with_no_files_still_lists_at_zero(client):
    """NEGATIVE CONTROL: a monitored series with nothing downloaded must appear
    with an honest zero rather than being dropped from the library."""
    c, factory = client
    with factory() as session:
        session.add(Show(tvdb_id=9, title="Wanted", library_section="TV", monitored=True))
        session.commit()
    show = c.get("/api/shows").json()["items"][0]
    assert show["title"] == "Wanted"
    assert show["episode_count"] == 0
    assert show["total_size"] == 0


def test_the_show_list_never_scores_anything(client):
    """NEGATIVE CONTROL for the decision behind this screen: shows are not judged
    on whether they deserve their space, so nothing resembling a verdict may
    appear in the payload."""
    c, factory = client
    _show(factory, 1, "Scrubs", episodes=2)
    show = c.get("/api/shows").json()["items"][0]
    for forbidden in ("junk_score", "band", "verdict", "score", "keep_override"):
        assert forbidden not in show


def test_an_empty_library_answers_cleanly(client):
    """NEGATIVE CONTROL."""
    c, _ = client
    body = c.get("/api/shows").json()
    assert body["items"] == [] and body["total"] == 0
    assert c.get("/api/shows/sections").json() == []
