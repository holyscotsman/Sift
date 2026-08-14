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


def _mixed_resolution_show(factory, tvdb_id: int, *, common: str, rare: str, common_count: int):
    """A show mostly in one resolution with a stray episode in another."""
    from sift.db.models import Episode, MediaFile, Season, Show

    with factory() as session:
        session.add(Show(tvdb_id=tvdb_id, title=f"Show {tvdb_id}", in_plex=True))
        season = Season(show_id=tvdb_id, season_number=1)
        session.add(season)
        session.flush()
        for n in range(common_count + 1):
            episode = Episode(season_id=season.id, episode_number=n + 1, has_file=True)
            session.add(episode)
            session.flush()
            session.add(
                MediaFile(
                    episode_id=episode.id,
                    path=f"/tv/{tvdb_id}/e{n}.mkv",
                    size=1_000_000_000,
                    duration_ms=1_320_000,
                    resolution=rare if n == common_count else common,
                    video_codec="h264",
                    source="plex",
                )
            )
        session.commit()


def test_a_show_is_listed_at_the_resolution_most_of_it_is_in(client):
    """It was listed at the resolution *least* of it was in.

    The map was built by a dict comprehension over rows ordered by count
    descending, and a comprehension keeps the last value written — so the final
    row, the rarest resolution, won every time. A show that is nineteen episodes
    of 1080p and one of 480p was displayed as 480p.
    """
    c, factory = client
    _mixed_resolution_show(factory, 5001, common="1080p", rare="480p", common_count=19)

    body = c.get("/api/shows").json()
    shown = {item["tvdb_id"]: item["resolution"] for item in body["items"]}
    assert shown[5001] == "1080p"


def test_the_listed_resolution_is_not_simply_the_highest(client):
    """NEGATIVE CONTROL. Picking the best resolution present would also fix the
    test above and be just as wrong in the other direction — a mostly-SD show with
    one HD episode is an SD show."""
    c, factory = client
    _mixed_resolution_show(factory, 5002, common="480p", rare="1080p", common_count=19)

    body = c.get("/api/shows").json()
    shown = {item["tvdb_id"]: item["resolution"] for item in body["items"]}
    assert shown[5002] == "480p"


def test_the_show_list_does_not_scan_the_library_for_every_page(client):
    """Both aggregates join media_file to episode to season. Unscoped they read
    the whole TV library on every page of an infinite scroll — twice. Pinned
    structurally, because on SQLite the scan is local and costs nothing, which is
    exactly why it survived."""
    from sqlalchemy import event

    c, factory = client
    for n in range(3):
        _mixed_resolution_show(factory, 6000 + n, common="1080p", rare="480p", common_count=2)

    engine = factory.kw["bind"]
    unscoped: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        text = " ".join(statement.split()).upper()
        if "FROM SEASONS" in text and "JOIN MEDIA_FILES" in text and "SHOW_ID IN" not in text:
            unscoped.append(text)

    try:
        assert c.get("/api/shows?page=2&page_size=1").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert not unscoped, f"whole-library aggregate on a page request: {unscoped}"
