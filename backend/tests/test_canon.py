"""The internal canon: deterministic build, gates, and the Plex-only diff."""

from __future__ import annotations

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from sift.db.models import CanonMovie, CuratedListEntry, Movie, MustHaveSuggestion
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
        rows, total = canon.missing(session)
        missing_ids = {r.tmdb_id for r in rows}
    assert 1 not in missing_ids
    assert 4 in missing_ids  # monitored-but-not-downloaded still reads as missing
    assert total == len(missing_ids)


async def test_canon_refresh_without_tmdb_still_merges_curated(factory, settings):
    settings.tmdb.enabled = False
    with factory() as session:
        session.add(MustHaveSuggestion(tmdb_id=7, title="Offline Canon", status="suggested"))
        session.commit()
    stats = await canon.refresh(factory, settings)
    assert stats["written"] == 1
