"""The internal canon: deterministic build, gates, and the Plex-only diff."""

from __future__ import annotations

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from sift.db.models import (
    Action,
    ActionStatus,
    ActionType,
    CanonMovie,
    CuratedListEntry,
    Movie,
    MustHaveSuggestion,
)
from sift.services import canon


def _tmdb_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/movie/top_rated"):
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json={"results": [
                {"id": 1, "title": "Canon Classic", "release_date": "1994-01-01",
                 "vote_average": 8.9, "vote_count": 20000, "poster_path": "/a.jpg"},
                # Gate control: too few votes for the top-rated path.
                {"id": 2, "title": "Obscure Gem", "release_date": "2001-01-01",
                 "vote_average": 8.2, "vote_count": 120},
                # Gate control: rating below the top-rated floor.
                {"id": 3, "title": "Mediocre", "release_date": "2005-01-01",
                 "vote_average": 6.1, "vote_count": 4000},
            ]})
        return httpx.Response(200, json={"results": []})
    if request.url.path.endswith("/discover/movie"):
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json={"results": [
                # Blockbusters count by reach — a low rating is fine here.
                {"id": 4, "title": "Loud Blockbuster", "release_date": "2019-06-01",
                 "vote_average": 5.9, "vote_count": 9000, "poster_path": "/b.jpg"},
            ]})
        return httpx.Response(200, json={"results": []})
    return httpx.Response(404)


async def test_canon_refresh_builds_from_all_sources(factory, settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    with factory() as session:
        # Curated entry with a resolved tmdb id → canon via "cult classic".
        session.add(
            CuratedListEntry(list_name="cult", title="Cult Pick", year=1985, tmdb_id=5,
                             review_status="pending")
        )
        # The curated title also exists in the snapshot so canon can name it.
        session.add(Movie(tmdb_id=5, title="Cult Pick", year=1985, in_plex=True))
        # A gated must-have suggestion → canon via "curator pick".
        session.add(MustHaveSuggestion(tmdb_id=6, title="Curated Canon", year=1960,
                                       status="suggested", vote_average=8.1, vote_count=900))
        session.commit()

    stats = await canon.refresh(factory, settings, transport=httpx.MockTransport(_tmdb_handler))
    assert stats["written"] == 4  # 1 top-rated + 1 blockbuster + 1 cult + 1 curator

    with factory() as session:
        ids = {c.tmdb_id: c for c in session.scalars(select(CanonMovie))}
        assert set(ids) == {1, 4, 5, 6}
        assert "top rated" in ids[1].sources
        assert "blockbuster" in ids[4].sources
        assert "cult classic" in ids[5].sources
        assert "curator pick" in ids[6].sources
        # Negative controls: both gate failures stayed out.
        assert 2 not in ids and 3 not in ids


async def test_canon_missing_compares_against_plex_only(factory, settings):
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    await canon.refresh(factory, settings, transport=httpx.MockTransport(_tmdb_handler))
    with factory() as session:
        # Canon title 1 is IN Plex → not missing. Canon title 4 is only monitored
        # in Radarr (not in Plex) → still missing: Radarr is ignored on purpose.
        session.add(Movie(tmdb_id=1, title="Canon Classic", in_plex=True))
        session.add(Movie(tmdb_id=4, title="Loud Blockbuster", in_plex=False, monitored=True))
        session.commit()
        rows, total, _ = canon.missing(session)
        missing_ids = {r.tmdb_id for r in rows}
    assert 1 not in missing_ids
    assert 4 in missing_ids  # monitored-but-not-downloaded still reads as missing
    assert total == len(missing_ids)


async def test_requested_titles_drop_out_of_missing(factory, settings):
    """A request takes days to land, so a requested title must stop being offered —
    otherwise it sits there looking un-actioned and gets requested twice."""
    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")
    await canon.refresh(factory, settings, transport=httpx.MockTransport(_tmdb_handler))

    with factory() as session:
        # Two more canon titles so each negative control has something to act on.
        session.add(CanonMovie(tmdb_id=5, title="Staged Pick", vote_count=800))
        session.add(CanonMovie(tmdb_id=6, title="Failed Pick", vote_count=700))
        session.commit()
        assert {1, 4, 5, 6}.issubset({r.tmdb_id for r in canon.missing(session)[0]})

        # A request that actually left Sift.
        session.add(
            Action(
                type=ActionType.ADD,
                movie_tmdb_id=1,
                status=ActionStatus.EXECUTED,
                dry_run=False,
                payload={"via": "overseerr"},
            )
        )
        # Negative controls — none of these reached anything, so they stay missing:
        # a staged (dry-run) add, a proposal never executed, and a failed one.
        session.add(
            Action(
                type=ActionType.ADD, movie_tmdb_id=4, status=ActionStatus.EXECUTED, dry_run=True
            )
        )
        session.add(
            Action(
                type=ActionType.ADD, movie_tmdb_id=5, status=ActionStatus.PROPOSED, dry_run=False
            )
        )
        session.add(
            Action(
                type=ActionType.ADD, movie_tmdb_id=6, status=ActionStatus.FAILED, dry_run=False
            )
        )
        session.commit()

        rows, total, requested_total = canon.missing(session)
        after = {r.tmdb_id for r in rows}

    assert 1 not in after  # really requested → hidden
    assert {4, 5, 6}.issubset(after)  # staged / proposed / failed → still missing
    assert total == len(after)
    assert requested_total == 1  # hidden, but counted rather than silently gone


async def test_canon_refresh_without_tmdb_still_merges_curated(factory, settings):
    settings.tmdb.enabled = False
    with factory() as session:
        session.add(MustHaveSuggestion(tmdb_id=7, title="Offline Canon", status="suggested"))
        session.commit()
    stats = await canon.refresh(factory, settings)
    assert stats["written"] == 1


async def test_building_the_catalog_does_not_query_per_candidate(factory, settings):
    """Regression pin. The owner watches a spinner while this runs.

    Merging the sweep into the canon was written as `session.get` per candidate —
    plus a second one for any entry needing a title from the snapshot. The sweep
    is several hundred titles, so that is several hundred sequential SELECTs
    inside the request. Free on this SQLite; a network round trip each against a
    hosted database, which is the difference between a moment and a minute.
    """
    from sqlalchemy import event

    settings.tmdb.enabled = True
    settings.tmdb.api_key = SecretStr("k")

    def wide_handler(request: httpx.Request) -> httpx.Response:
        # Two hundred candidates, so a per-candidate shape is unmistakable.
        if request.url.path.endswith("/movie/top_rated") and request.url.params.get("page") == "1":
            return httpx.Response(200, json={"results": [
                {"id": 1000 + i, "title": f"Canon {i}", "release_date": "1994-01-01",
                 "vote_average": 8.9, "vote_count": 20000}
                for i in range(200)
            ]})
        return httpx.Response(200, json={"results": []})

    statements = {"n": 0}
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_a, **_kw):
        statements["n"] += 1

    try:
        result = await canon.refresh(
            factory, settings, transport=httpx.MockTransport(wide_handler)
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # NEGATIVE CONTROL: a merge that wrote nothing would satisfy any statement
    # budget. The rows have to actually be there.
    assert result["written"] == 200
    with factory() as session:
        assert session.query(CanonMovie).count() == 200

    # Per-candidate lookups would be 200+. Preloaded is a handful either way.
    assert statements["n"] < 25, f"{statements['n']} statements for 200 candidates"
