"""Which Plex libraries get read, and as what.

The case that matters: a Home Videos library is Plex type ``movie``, so without
this it is ingested as films — into the removal queue, the film counts, and the
bitrate baselines every size verdict is measured against.
"""

from __future__ import annotations

from sift.ingest import sections


def _section(title: str, kind: str, agent: str | None = "tv.plex.agents.series", key: str = "1"):
    raw = {"key": key, "title": title, "type": kind}
    if agent is not None:
        raw["agent"] = agent
    return raw


# ------------------------------------------------------- every show library is TV


def test_cartoons_anime_and_game_shows_are_all_television():
    """Nothing here keys off the word 'TV'. A show library is a show library
    whatever it is called, so the split needs no per-library setup."""
    for title in ("TV Shows", "Cartoons", "Anime", "Game Shows", "Documentaries"):
        plan = sections.plan_section(_section(title, "show"))
        assert plan.kind == sections.SHOW, title
        assert plan.scanned


def test_a_film_library_stays_film():
    plan = sections.plan_section(_section("Movies", "movie", "tv.plex.agents.movie"))
    assert plan.kind == sections.MOVIE


# ------------------------------------------------------------------ home videos


def test_home_videos_are_left_alone():
    """Plex calls this a movie library. Ingesting it puts family footage in the
    removal queue and drags the 1080p baseline somewhere meaningless."""
    plan = sections.plan_section(_section("Home Videos", "movie", "com.plexapp.agents.none"))
    assert plan.kind == sections.IGNORE
    assert not plan.scanned
    assert "no metadata agent" in plan.reason


def test_it_is_the_agent_that_decides_not_the_name():
    """NEGATIVE CONTROL: matching on the title would miss the same library called
    'Camcorder', or in another language, and would wrongly drop a real film
    library that happens to be called 'Home Cinema'."""
    camcorder = sections.plan_section(_section("Camcorder", "movie", "com.plexapp.agents.none"))
    assert camcorder.kind == sections.IGNORE

    home_cinema = sections.plan_section(_section("Home Cinema", "movie", "tv.plex.agents.movie"))
    assert home_cinema.kind == sections.MOVIE


def test_a_section_that_reports_no_agent_field_is_still_scanned():
    """NEGATIVE CONTROL, and the dangerous one. Inferring 'personal media' from a
    missing field would make a scan silently read nothing — which looks exactly
    like a successful scan of an empty library."""
    plan = sections.plan_section({"key": "1", "title": "Movies", "type": "movie"})
    assert plan.kind == sections.MOVIE
    assert plan.scanned


# ----------------------------------------------------------------- other types


def test_music_and_photos_are_not_video():
    for kind in ("artist", "photo"):
        assert sections.plan_section(_section("Stuff", kind)).kind == sections.IGNORE


# ------------------------------------------------------------------- overrides


def test_the_owner_can_correct_any_of_it():
    overrides = {"Concerts": "show", "Movies": "ignore", "Kids Stuff": "movie"}
    assert sections.plan_section(_section("Concerts", "movie"), overrides).kind == sections.SHOW
    assert sections.plan_section(_section("Movies", "movie"), overrides).kind == sections.IGNORE
    assert sections.plan_section(_section("Kids Stuff", "show"), overrides).kind == sections.MOVIE


def test_an_override_says_so():
    plan = sections.plan_section(_section("Concerts", "movie"), {"Concerts": "show"})
    assert plan.overridden and plan.reason == "set by you"


def test_a_nonsense_override_is_ignored_rather_than_obeyed():
    """NEGATIVE CONTROL: a bad value must fall back to Plex's own type, not
    silently drop the library or invent a third kind."""
    plan = sections.plan_section(_section("Movies", "movie"), {"Movies": "banana"})
    assert plan.kind == sections.MOVIE
    assert not plan.overridden


def test_planning_the_whole_server():
    plans = sections.plan(
        [
            _section("Movies", "movie", "tv.plex.agents.movie", key="1"),
            _section("Anime", "show", key="2"),
            _section("Home Videos", "movie", "com.plexapp.agents.none", key="3"),
            _section("Music", "artist", key="4"),
        ]
    )
    assert {p.title: p.kind for p in plans} == {
        "Movies": sections.MOVIE,
        "Anime": sections.SHOW,
        "Home Videos": sections.IGNORE,
        "Music": sections.IGNORE,
    }
    assert [p.title for p in plans if p.scanned] == ["Movies", "Anime"]
